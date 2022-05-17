from operator import ipow
from .loss_factory import Loss_factory
from .pixel_loss import PixelLoss, PixelLossWithDepth
from .pixel_loss import PixelLossWithDepthAndSight
from .pixel_loss import PixelLossWithSightAndNear
from .sparsity_loss import SparsityLoss, CauchySparsityLoss
from .composite_loss import CompositeLoss


Loss_factory.register('PixelLoss', PixelLoss)
Loss_factory.register('PixelLossWithDepth', PixelLossWithDepth)
Loss_factory.register('PixelLossWithDepthAndSight', PixelLossWithDepthAndSight)
Loss_factory.register('PixelLossWithSightAndNear', PixelLossWithSightAndNear)
Loss_factory.register('SparsityLoss', SparsityLoss)
Loss_factory.register('CauchySparsityLoss', CauchySparsityLoss)
Loss_factory.register('CompositeLoss', CompositeLoss)


__all__ = ['Loss_factory']
