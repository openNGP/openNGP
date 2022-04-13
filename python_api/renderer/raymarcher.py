import torch
import numpy as np
from collections import namedtuple
from python_api.renderer.raymarching import near_far_from_aabb
from python_api.renderer.rays import Rays, RaysWithDepth
from python_api.utils import FunctionRegistry


SamplerResult = namedtuple(
    'SamplerResult',
    ('xyzs', 'views', 'z_vals', 'deltas')
)


# Hierarchical sampling (section 5.2)
def sample_pdf(bins, weights, N_samples, det=False, pytest=False):
    # Get pdf
    device = weights.device
    weights = weights + 1e-5 # prevent nans
    pdf = weights / torch.sum(weights, -1, keepdim=True)
    cdf = torch.cumsum(pdf, -1)
    cdf = torch.cat([torch.zeros_like(cdf[...,:1]), cdf], -1)  # (batch, len(bins))

    # Take uniform samples
    if det:
        u = torch.linspace(0., 1., steps=N_samples, device=device)
        u = u.expand(list(cdf.shape[:-1]) + [N_samples], device=device)
    else:
        u = torch.rand(list(cdf.shape[:-1]) + [N_samples], device=device)

    # Pytest, overwrite u with numpy's fixed random numbers
    if pytest:
        np.random.seed(0)
        new_shape = list(cdf.shape[:-1]) + [N_samples]
        if det:
            u = np.linspace(0., 1., N_samples)
            u = np.broadcast_to(u, new_shape)
        else:
            u = np.random.rand(*new_shape)
        u = torch.Tensor(u)

    # Invert CDF
    u = u.contiguous()
    inds = torch.searchsorted(cdf, u, right=True)
    below = torch.max(torch.zeros_like(inds-1), inds-1)
    above = torch.min((cdf.shape[-1]-1) * torch.ones_like(inds), inds)
    inds_g = torch.stack([below, above], -1)  # (batch, N_samples, 2)

    # cdf_g = tf.gather(cdf, inds_g, axis=-1, batch_dims=len(inds_g.shape)-2)
    # bins_g = tf.gather(bins, inds_g, axis=-1, batch_dims=len(inds_g.shape)-2)
    matched_shape = [inds_g.shape[0], inds_g.shape[1], cdf.shape[-1]]
    cdf_g = torch.gather(cdf.unsqueeze(1).expand(matched_shape), 2, inds_g)
    bins_g = torch.gather(bins.unsqueeze(1).expand(matched_shape), 2, inds_g)

    denom = (cdf_g[...,1]-cdf_g[...,0])
    denom = torch.where(denom<1e-5, torch.ones_like(denom), denom)
    t = (u-cdf_g[...,0])/denom
    samples = bins_g[...,0] + t * (bins_g[...,1]-bins_g[...,0])

    return samples


def delta_from_zval(z_vals, rays_d, delta_inf=1e10):
    # Convert these values using volume rendering (Section 4)
    deltas = z_vals[:, 1:] - z_vals[:, :-1] # (N_rays, N_samples_-1)
    delta_inf = delta_inf * torch.ones_like(deltas[:, :1]) # (N_rays, 1) the last delta is infinity
    deltas = torch.cat([deltas, delta_inf], -1)  # (N_rays, N_samples_)
    deltas = deltas * torch.norm(rays_d[...,None,:], dim=-1)
    return deltas


def uniform_sampler(rays: Rays, N_samples: int, lindisp: bool, perturb: bool):
    near, far = rays.near, rays.far
    rays_o, rays_d = rays.origins, rays.directions
    N_rays = rays_o.shape[0]

    t_vals = torch.linspace(0., 1., steps=N_samples)
    if not lindisp:
        z_vals = near * (1.-t_vals) + far * (t_vals)
    else:
        z_vals = 1./(1./near * (1.-t_vals) + 1./far * (t_vals))

    z_vals = z_vals.expand([N_rays, N_samples])

    if perturb > 0.:
        # get intervals between samples
        mids = .5 * (z_vals[...,1:] + z_vals[...,:-1])
        upper = torch.cat([mids, z_vals[...,-1:]], -1)
        lower = torch.cat([z_vals[...,:1], mids], -1)
        # stratified samples in those intervals
        t_rand = torch.rand(z_vals.shape)

        z_vals = lower + (upper - lower) * t_rand

    pts = rays_o[...,None,:] + rays_d[...,None,:] * z_vals[...,:,None] # [N_rays, N_samples, 3]
    
    # Convert these values using volume rendering (Section 4)
    deltas = delta_from_zval(z_vals, rays_d)

    views = rays.viewdirs[...,None,:].expand(pts.shape)

    return SamplerResult(pts, views, z_vals, deltas)


def importance_sampler(rays: Rays,
                       samples: SamplerResult,  # samples from last pass
                       weights,
                       N_importance,
                       perturb):
    rays_o, rays_d = rays.origins, rays.directions
    z_vals = samples.z_vals
    z_vals_mid = .5 * (z_vals[...,1:] + z_vals[...,:-1])
    z_samples = sample_pdf(z_vals_mid, weights[...,1:-1], N_importance, det=(perturb==0.))
    z_samples = z_samples.detach()

    z_vals, _ = torch.sort(torch.cat([z_vals, z_samples], -1), -1)
    pts = rays_o[...,None,:] + rays_d[...,None,:] * z_vals[...,:,None] # [N_rays, N_samples + N_importance, 3]

    # Convert these values using volume rendering (Section 4)
    deltas = delta_from_zval(z_vals, rays_d)

    views = rays.viewdirs[...,None,:].expand(pts.shape)
    
    return SamplerResult(pts, views, z_vals, deltas)


def instant_ngp_sampler(rays: Rays, bound, num_steps, min_near, perturb):
    rays_o, rays_d = rays.origins, rays.viewdirs  # rays.directions isn't normalized
    device = rays_o.device
    prefix = rays_o.shape[:-1]
    rays_o = rays_o.contiguous().view(-1, 3)
    rays_d = rays_d.contiguous().view(-1, 3)

    N = rays_o.shape[0] # N = B * N, in fact
    device = rays_o.device

    # choose aabb
    aabb = torch.Tensor([-bound, -bound, -bound, bound, bound, bound])
    aabb = aabb.to(device)

    # sample steps
    nears, fars = near_far_from_aabb(rays_o, rays_d, aabb, min_near)
    nears.unsqueeze_(-1)
    fars.unsqueeze_(-1)

    #print(f'nears = {nears.min().item()} ~ {nears.max().item()}, fars = {fars.min().item()} ~ {fars.max().item()}')

    z_vals = torch.linspace(0.0, 1.0, num_steps, device=device).unsqueeze(0) # [1, T]
    z_vals = z_vals.expand((N, num_steps)) # [N, T]
    z_vals = nears + (fars - nears) * z_vals # [N, T], in [nears, fars]

    # perturb z_vals
    sample_dist = (fars - nears) / num_steps
    if perturb:
        z_vals = z_vals + (torch.rand(z_vals.shape, device=device) - 0.5) * sample_dist
        #z_vals = z_vals.clamp(nears, fars) # avoid out of bounds xyzs.

    # generate xyzs
    pts = rays_o.unsqueeze(-2) + rays_d.unsqueeze(-2) * z_vals.unsqueeze(-1) # [N, 1, 3] * [N, T, 1] -> [N, T, 3]
    pts = torch.min(torch.max(pts, aabb[:3]), aabb[3:]) # a manual clip.

    # Convert these values using volume rendering (Section 4)
    deltas = delta_from_zval(z_vals, rays_d, sample_dist)

    views = rays.viewdirs[...,None,:].expand(pts.shape)

    return SamplerResult(pts, views, z_vals, deltas)


def ngp_sampler_with_depth(rays: RaysWithDepth, bound, num_steps, min_near, perturb, epsilon):
    rays_o, rays_d = rays.origins, rays.viewdirs  # rays.directions isn't normalized
    device = rays_o.device
    prefix = rays_o.shape[:-1]
    rays_o = rays_o.contiguous().view(-1, 3)
    rays_d = rays_d.contiguous().view(-1, 3)

    N = rays_o.shape[0] # N = B * N, in fact
    device = rays_o.device

    # choose aabb
    aabb = torch.Tensor([-bound, -bound, -bound, bound, bound, bound])
    aabb = aabb.to(device)

    # sample steps
    nears, fars = near_far_from_aabb(rays_o, rays_d, aabb, min_near)
    nears.unsqueeze_(-1)
    fars.unsqueeze_(-1)

    #print(f'nears = {nears.min().item()} ~ {nears.max().item()}, fars = {fars.min().item()} ~ {fars.max().item()}')

    z_vals = torch.linspace(0.0, 1.0, num_steps, device=device).unsqueeze(0) # [1, T]
    z_vals = z_vals.expand((N, num_steps)) # [N, T]
    z_vals = nears + (fars - nears) * z_vals # [N, T], in [nears, fars]

    # perturb z_vals
    sample_dist = (fars - nears) / num_steps
    if perturb:
        z_vals = z_vals + (torch.rand(z_vals.shape, device=device) - 0.5) * sample_dist
        #z_vals = z_vals.clamp(nears, fars) # avoid out of bounds xyzs.

    # sample from depth prior, N(d_prior, epsilon)
    extra_z_vals = torch.zeros_like(z_vals)
    valid_depth = rays.depth[rays.mask]
    m = torch.distributions.Normal(valid_depth, epsilon*torch.ones_like(valid_depth))
    depth_samples = m.sample(torch.Size([num_steps]))
    extra_z_vals[rays.mask.squeeze()] = depth_samples.T

    # sample from
    m = torch.distributions.Uniform(nears[~rays.mask], fars[~rays.mask])
    pad_samples = m.sample(torch.Size([num_steps]))
    extra_z_vals[~rays.mask.squeeze()] = pad_samples.T

    z_vals, _ = torch.sort(torch.cat([z_vals, extra_z_vals], -1), -1)

    # generate xyzs
    pts = rays_o.unsqueeze(-2) + rays_d.unsqueeze(-2) * z_vals.unsqueeze(-1) # [N, 1, 3] * [N, T, 1] -> [N, T, 3]
    pts = torch.min(torch.max(pts, aabb[:3]), aabb[3:]) # a manual clip.

    # Convert these values using volume rendering (Section 4)
    deltas = delta_from_zval(z_vals, rays_d, sample_dist)

    views = rays.viewdirs[...,None,:].expand(pts.shape)

    return SamplerResult(pts, views, z_vals, deltas)


raymarcher = FunctionRegistry(
    uniform_sampler=uniform_sampler,
    importance_sampler=importance_sampler,
    instant_ngp_sampler=instant_ngp_sampler,
    ngp_sampler_with_depth=ngp_sampler_with_depth
)
