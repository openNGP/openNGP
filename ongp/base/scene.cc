
#include "ongp/base/scene.h"

namespace ongp
{
    void Scene::Add(ObjectSptr object)
    {
        objects_.push_back(object);
    }

    bool Scene::Hit(const Ray& r, double t_min, double t_max, RayHit& hit) const
    {
        double max_t = std::numeric_limits<double>::max();
        double hit_or_not = false;
        for (auto& object : objects_)
        {
            RayHit rh;
            if (object->Hit(r, t_min, t_max, rh) && !object->OnSurface(r.origin()))
            {
                hit_or_not = true;
                if (rh.t < max_t)
                {
                    hit = rh;
                    max_t = rh.t;
                }
            }
        }
        return hit_or_not;
    }

    bool Scene::OnSurface(const torch::Tensor& point) const
    {
        for (auto& object : objects_)
        {
            if (object->OnSurface(point))
                return true;
        }
        return false;
    }

    bool Scene::BoundingBox(AABB& output_box) const
    {
        if (objects_.empty()) return false;

        AABB temp_box;
        bool first_box = true;

        for (const auto& object : objects_) {
            if (!object->BoundingBox(temp_box)) return false;
            output_box = first_box ? temp_box : SurroundingBox(output_box, temp_box);
            first_box = false;
        }

        return true;
    }
}