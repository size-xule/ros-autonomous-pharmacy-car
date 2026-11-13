#pragma once

#include <array>
#include <cmath>
#include <optional>
#include <string>

namespace eprobot_base {

inline constexpr double kWheelDiameterM = 0.065;
inline constexpr double kPhysicalWheelDiameterM = 0.065;
inline constexpr double kWheelBaseM = 0.155;
inline constexpr double kAxleM = 0.160;
inline constexpr double kDefaultBaseKv = 1.0;
inline constexpr double kDefaultMaxVxMps = 1.0;
inline constexpr double kFirmwareMaxVxMps = 1.5;

double clamp(double value, double low, double high);
double wrap_deg(double angle_deg);
double wrap_rad(double angle_rad);
double nearest_equivalent(double angle_rad, double reference_rad);
double extrapolate_yaw(double yaw_deg, double gyro_dps, int age_ms,
                       bool imu_ok = true, bool cal_failed = false,
                       double dlpf_delay_ms = 3.0);

struct Setpoint {
  int vx_mm_s = 0;
  int delta_mrad = 0;
  double vx_mps = 0.0;
  double omega_rad_s = 0.0;
  bool limited = false;
  bool turning_in_place = false;
  std::string reason;

  double delta_rad() const { return delta_mrad / 1000.0; }
  bool is_zero() const { return vx_mm_s == 0 && delta_mrad == 0; }
};

Setpoint cmd_vel_to_setpoint(double vx_mps, double omega_rad_s,
                             double wheelbase_m = kAxleM,
                             double max_vx_mps = kDefaultMaxVxMps,
                             int steer_max_mrad = 567,
                             double min_turn_speed_mps = 0.0,
                             double min_vx_mps = 0.0,
                             double speed_scale = 1.0);

std::array<double, 2> wheel_speeds(double vx_mps, double omega_rad_s,
                                   double track_m = kWheelBaseM);
double ackermann_radius(double vx_mps, int delta_mrad,
                        double wheelbase_m = kAxleM);

// (x, y, z, w) for a pure yaw rotation.
std::array<double, 4> quaternion_from_yaw(double yaw_rad);
double quaternion_to_yaw(double x, double y, double z, double w);
double quaternion_to_yaw(const std::array<double, 4>& quaternion);

class OdomIntegrator {
 public:
  OdomIntegrator(double x = 0.0, double y = 0.0, double yaw_rad = 0.0);

  void reset(double x = 0.0, double y = 0.0, double yaw_rad = 0.0);
  void update(double vx_mps, std::optional<double> yaw_deg, double dt);
  void update_gyro(double vx_mps, double gyro_dps, double dt);

  double x = 0.0;
  double y = 0.0;
  double yaw = 0.0;
  std::optional<double> last_update;
};

}  // namespace eprobot_base
