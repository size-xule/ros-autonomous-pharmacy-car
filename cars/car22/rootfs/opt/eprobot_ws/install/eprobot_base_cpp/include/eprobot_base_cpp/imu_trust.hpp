#pragma once

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace eprobot_base {

inline constexpr std::uint8_t kImuAgeInvalid = 255;

inline bool telemetry_imu_trusted(bool imu_ok, bool cal_failed, int age_ms) {
  return imu_ok && !cal_failed && age_ms != kImuAgeInvalid;
}

inline bool covariance_available(const double* covariance, std::size_t size) {
  if (covariance == nullptr || size < 1) {
    return false;
  }
  const double first = covariance[0];
  return std::isfinite(first) && first >= 0.0;
}

inline bool covariance_available(const std::vector<double>& covariance) {
  return covariance_available(covariance.data(), covariance.size());
}

template <typename ImuMessage>
bool imu_message_usable(const ImuMessage& msg) {
  return covariance_available(msg.orientation_covariance.data(),
                              msg.orientation_covariance.size()) &&
         covariance_available(msg.angular_velocity_covariance.data(),
                              msg.angular_velocity_covariance.size()) &&
         covariance_available(msg.linear_acceleration_covariance.data(),
                              msg.linear_acceleration_covariance.size());
}

}  // namespace eprobot_base
