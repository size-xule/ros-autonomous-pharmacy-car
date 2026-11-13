#pragma once

// Judge wire format helpers, split out of judge_tcp_node.cpp so the encoder can
// be replayed offline (test/mission_backtest.cpp). Depends only on nlohmann/json.

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <set>
#include <string>

namespace pharmacy {
namespace judge {

using Json = nlohmann::json;

// Keep the wire protocol ASCII even with Chinese board text on older json.hpp.
// Input is a JSON::dump() string; output is the same text with every non-ASCII
// code point rewritten as a \uXXXX escape, terminated by exactly one newline.
inline std::string asciiJsonLine(const std::string& utf8_json_dump) {
  const char* hex = "0123456789abcdef";
  std::string result;
  result.reserve(utf8_json_dump.size() + 16);
  auto escape = [&](unsigned c) {
    result += "\\u";
    for (int shift = 12; shift >= 0; shift -= 4) result += hex[(c >> shift) & 15];
  };
  for (std::size_t i = 0; i < utf8_json_dump.size();) {
    unsigned c = static_cast<unsigned char>(utf8_json_dump[i++]);
    if (c < 128) {
      result += static_cast<char>(c);
      continue;
    }
    const int count = c >= 0xc2 && c <= 0xdf ? 1 : c >= 0xe0 && c <= 0xef ? 2
                      : c >= 0xf0 && c <= 0xf4 ? 3
                                               : 0;
    unsigned cp = count ? c & ((1u << (6 - count)) - 1) : 0xfffd;
    bool valid = count != 0;
    const unsigned minimum = count == 1 ? 0x80 : count == 2 ? 0x800 : 0x10000;
    for (int k = 0; k < count; ++k) {
      if (i >= utf8_json_dump.size() ||
          (static_cast<unsigned char>(utf8_json_dump[i]) & 0xc0) != 0x80) {
        valid = false;
        break;
      }
      cp = (cp << 6) | (static_cast<unsigned char>(utf8_json_dump[i++]) & 63);
    }
    if (!valid || cp < minimum || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) {
      cp = 0xfffd;
    }
    if (cp <= 0xffff) {
      escape(cp);
    } else {
      cp -= 0x10000;
      escape(0xd800 + (cp >> 10));
      escape(0xdc00 + (cp & 1023));
    }
  }
  return result + '\n';
}

// Python 2 round() compatibility used by the original judge node: round the
// original binary value, not an already-rounded multiplication.
inline double roundedMillis(double value) {
  if (!std::isfinite(value)) return 0.0;
  const double magnitude = std::abs(value), scaled = magnitude * 1000.0;
  if (!std::isfinite(scaled)) return value;
  double integral = std::round(scaled);
  if (scaled - std::floor(scaled) == 0.5 && std::fma(magnitude, 1000.0, -scaled) < 0.0) {
    integral = std::floor(scaled);
  }
  return std::copysign(integral / 1000.0, value);
}

inline bool isAcceptedTask(const std::string& task) {
  static const std::set<std::string> accepted = {"A", "B", "C", "AB",
                                                 "AC", "BC", "ABC"};
  return accepted.count(task) != 0;
}

inline std::string acceptedTask(const std::string& task) {
  return isAcceptedTask(task) ? task : std::string();
}

// /cmd_send fallback: 2 + /dispense_window selects C/A/B, 6 + /pick_up_num
// selects window 4..1. Out-of-range input is ignored, as in ROS 1.
inline std::string taskFromCommand(int command, int dispense, int pickup) {
  if (command == 2 && dispense >= 0 && dispense <= 2) {
    return std::string(1, "CAB"[dispense]);
  }
  if (command == 6 && pickup >= 3 && pickup <= 6) {
    return std::to_string(7 - pickup);
  }
  return {};
}

struct Snapshot {
  std::string id;
  double speed = 0.0;
  double x = 0.0;
  double y = 0.0;
  std::string task;
  std::string cv1;
  std::string cv2;
};

inline std::string snapshotLine(const Snapshot& snapshot) {
  const Json value{{"id", snapshot.id},
                   {"speed", roundedMillis(snapshot.speed)},
                   {"odom", Json::array({roundedMillis(snapshot.x),
                                         roundedMillis(snapshot.y)})},
                   {"task", acceptedTask(snapshot.task)},
                   {"CV1", snapshot.cv1},
                   {"CV2", snapshot.cv2}};
  return asciiJsonLine(value.dump());
}

inline double growReconnectDelay(double current, double maximum) {
  return std::min(maximum, current * 2.0);
}

}  // namespace judge
}  // namespace pharmacy
