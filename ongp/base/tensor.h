#pragma once

#include <torch/torch.h>

namespace ongp
{
    namespace 
    {
    template <class T>
    using Array1d = std::vector<T>;

    template <class T>
    using Array2d = std::vector<std::vector<T>>;

    template <class T>
    using Array3d = std::vector<std::vector<std::vector<T>>>;

    template <class T>
    std::vector<T> Linearize2d(const std::vector<std::vector<T>>& array_2d) {
        std::vector<T> array;
        for (const auto& v : array_2d) {
            for (auto d : v) {
                array.push_back(d);
            }
        }
        return array;
    }

    template <class T>
    torch::Tensor Array2dToTensor(const Array2d<T>& array_2d)
    {
        int m = array_2d.size();
        int n = array_2d[0].size();

        // torch::from_blob do not copy original data buffer!
        return torch::from_blob(Linearize2d(array_2d).data(), {m,n}).clone();
    }

    template <class T>
    torch::Tensor Array1dToTensor(const Array1d<T>& array_1d)
    {
        int m = array_1d.size();

        // torch::from_blob do not copy original data buffer!
        return torch::from_blob(const_cast<T*>(array_1d.data()), {m}).clone();
    }

    inline double random_double()
    {
        return rand() / (RAND_MAX+1);
    }

    inline double random_double(double min, double max)
    {
        return min + (max - min) * random_double();
    }

    inline torch::Tensor random_vec3()
    {
        return Array1dToTensor<double>({random_double(), random_double(), random_double()});
    }

    inline torch::Tensor random_vec3(double min, double max)
    {
        return Array1dToTensor<double>({random_double(min, max), random_double(min, max), random_double(min, max)});
    }

    inline torch::Tensor random_in_sphere()
    {
        while(true)
        {
            auto p = random_vec3(-1, 1);
            if (p.norm().item<float>() >= 1) continue;
            return p;
        }
    }

    inline double clamp(double x, double min, double max) {
        if (x < min) return min;
        if (x > max) return max;
        return x;
    }
    }
}
