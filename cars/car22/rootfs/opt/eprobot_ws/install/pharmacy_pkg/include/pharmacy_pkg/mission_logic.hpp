#pragma once

// Pure mission rules shared by f1_mission_node and the offline backtest.
// Nothing here depends on rclcpp, so test/mission_backtest.cpp can be built
// with a plain host compiler.

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <string>
#include <vector>

namespace pharmacy {
namespace mission {

struct Waypoint {
  double x = 0.0;
  double y = 0.0;
  double yaw = 0.0;
};

struct WaypointParse {
  bool ok = false;
  Waypoint value{};
  std::string error;
};

inline WaypointParse parseWaypoint(const std::vector<double>& values,
                                   const std::string& name) {
  if (values.size() != 3) {
    return {false, {}, "Waypoint must be [x,y,yaw]: " + name};
  }
  Waypoint point;
  double coordinates[3] = {0.0, 0.0, 0.0};
  for (std::size_t i = 0; i < 3; ++i) {
    if (!std::isfinite(values[i])) {
      return {false, {}, "Waypoint must be finite: " + name};
    }
    coordinates[i] = values[i];
  }
  point.x = coordinates[0];
  point.y = coordinates[1];
  point.yaw = coordinates[2];
  return {true, point, {}};
}

// `match_seconds == 0` is the continuous mode: the sample budget is ignored
// and capacity never shrinks (mirrors the ROS 1 node).
inline int roundCapacity(bool timed, int max_samples, int delivered) {
  return timed ? std::max(0, max_samples - delivered) : max_samples;
}

inline bool roundComplete(bool timed, int rounds, int max_rounds, int delivered,
                          int max_samples) {
  return timed && (rounds >= max_rounds || delivered >= max_samples);
}

// A round never picks more samples than the remaining budget, even when the
// QR task itself asked for more windows.
inline std::string eligibleLetters(const std::string& task_letters, int capacity) {
  if (capacity <= 0) return {};
  return task_letters.substr(0, static_cast<std::size_t>(capacity));
}

// The A/B heading override is decided by the *original* QR task, not by the
// truncated letter list (ROS 1 test_capacity_truncates_original_qr_and_heading).
inline double pickupYaw(bool letters_contain_a, bool letters_contain_b,
                        double configured_heading) {
  return letters_contain_a && letters_contain_b ? M_PI / 6.0 : configured_heading;
}

inline std::string roundLabel(const std::string& letters, const std::string& window) {
  return letters + "-" + window;
}

enum class NavOutcome { Aborted, Canceled, Rejected, Unknown };

// ROS 1 actionlib terminal-state codes kept on the wire/evidence log. A
// successful goal is not recorded as a failure; a rejected goal (REJECTED) is
// reported when the ROS 2 goal response is null.
inline int navResultCode(NavOutcome outcome) {
  switch (outcome) {
    case NavOutcome::Aborted:
      return 4;
    case NavOutcome::Canceled:
      return 2;
    case NavOutcome::Rejected:
      return 5;
    case NavOutcome::Unknown:
    default:
      return 9;
  }
}

// An unrecognized or timed-out board2 reading is treated as FREE, matching the
// competition safety rule in the ROS 1 node.
inline std::string boardValue(bool recognized, const std::string& reported) {
  return recognized ? reported : "FREE";
}

inline double boardWaitFrom(double speech_done, double now_seconds, int seconds) {
  return std::max(0.0, speech_done + static_cast<double>(seconds) - now_seconds);
}

inline bool isTerminalSpeechStatus(const std::string& state) {
  return state == "DONE" || state == "FAILED" || state == "MISSING" ||
         state == "QUEUE_FULL";
}

// Exact ordering of the ROS 1 post-loop status rewrite: motion is applied
// first, then a dead/interrupted mission overwrites it, and only a live
// mission rewrites the PLAYING/empty case to TIMEOUT.
inline std::string finalSpeechStatus(bool alive, bool motion_detected,
                                     const std::string& state) {
  const std::string result = motion_detected ? "MOTION_DETECTED" : state;
  if (!alive) return "INTERRUPTED";
  if (result.empty() || result == "PLAYING") return "TIMEOUT";
  return result;
}

inline bool speechSucceeded(const std::string& final_status, bool evidence_saved) {
  return final_status == "DONE" && evidence_saved;
}

}  // namespace mission
}  // namespace pharmacy
