#pragma once
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/int32.hpp>
#include <std_msgs/msg/string.hpp>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <regex>
#include <stdexcept>
#include <string>
#include <vector>

namespace pharmacy {
using Json = nlohmann::json;

inline rclcpp::NodeOptions nodeOptions() {
  rclcpp::NodeOptions options;
  options.automatically_declare_parameters_from_overrides(true);
  return options;
}

inline double now() {
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

inline std::string expandHome(std::string path) {
  const char* home = std::getenv("HOME");
  if (home && path.compare(0, 2, "~/") == 0) path = std::string(home) + path.substr(1);
  return path;
}

inline void appendJson(const std::string& path, const Json& record) {
  const std::filesystem::path parent = std::filesystem::path(path).parent_path();
  if (!parent.empty()) std::filesystem::create_directories(parent);
  std::ofstream stream(path, std::ios::app);
  stream << record.dump() << '\n';
  if (!stream) throw std::runtime_error("Cannot write " + path);
}

// ROS 1 latched topics map to transient-local durability in ROS 2.
inline rclcpp::QoS latchedQos() {
  return rclcpp::QoS(rclcpp::KeepLast(1)).transient_local().reliable();
}

inline rclcpp::QoS sensorQos() {
  return rclcpp::SensorDataQoS();
}

inline void publish(const rclcpp::Publisher<std_msgs::msg::String>::SharedPtr& p,
                    const std::string& value) {
  std_msgs::msg::String message;
  message.data = value;
  p->publish(message);
}
inline void publish(const rclcpp::Publisher<std_msgs::msg::String>::SharedPtr& p,
                    const char* value) {
  publish(p, std::string(value));
}
inline void publish(const rclcpp::Publisher<std_msgs::msg::Bool>::SharedPtr& p, bool value) {
  std_msgs::msg::Bool message;
  message.data = value;
  p->publish(message);
}
inline void publish(const rclcpp::Publisher<std_msgs::msg::Int32>::SharedPtr& p, int value) {
  std_msgs::msg::Int32 message;
  message.data = value;
  p->publish(message);
}

template <typename T>
T param(rclcpp::Node& node, const std::string& key, const T& fallback) {
  if (!node.has_parameter(key)) return node.declare_parameter<T>(key, fallback);
  return node.get_parameter(key).get_value<T>();
}

inline double bounded(rclcpp::Node& node, const std::string& key, double fallback,
                      double lo, double hi) {
  const double value = param<double>(node, key, fallback);
  if (!std::isfinite(value)) throw std::invalid_argument("Non-finite parameter: " + key);
  return std::max(lo, std::min(hi, value));
}

inline std::string trim(const std::string& s) {
  const auto first = s.find_first_not_of(" \t\r\n");
  return first == std::string::npos
             ? ""
             : s.substr(first, s.find_last_not_of(" \t\r\n") - first + 1);
}

struct Task {
  std::string letters, window, cv2;
  int encoded = 0;
};

inline bool cameraTask(const std::vector<int32_t>& v, Task& task) {
  if (v.size() != 5 || v[4] < 3 || v[4] > 6) return false;
  for (int i = 0; i < 3; ++i)
    if (v[i] != 0 && v[i] != 1) return false;
  std::string letters;
  if (v[1]) letters += 'A';
  if (v[2]) letters += 'B';
  if (v[0]) letters += 'C';
  if (letters.empty() || v[3] != static_cast<int>(letters.size())) return false;
  task = {letters, std::to_string(7 - v[4]), letters + "-" + std::to_string(7 - v[4]), v[4]};
  return true;
}

struct BoardStatus {
  std::string value;
  int seconds = 0;
};

inline bool boardStatus(std::string text, BoardStatus& result) {
  text.erase(std::remove_if(text.begin(), text.end(),
                            [](unsigned char c) { return c < 128 && std::isspace(c); }),
             text.end());
  for (char& c : text)
    if (static_cast<unsigned char>(c) < 128) c = std::toupper(c);
  if (text == "FREE" || (text.find("化验区空闲") != std::string::npos &&
                         text.find("快速通过") != std::string::npos)) {
    result = {"FREE", 0};
    return true;
  }
  std::smatch match;
  if (std::regex_match(text, match, std::regex("BUSY_([0-9]{1,2})")) ||
      (text.find("化验区忙碌") != std::string::npos &&
       std::regex_search(text, match, std::regex("等待([0-9]{1,2})秒")))) {
    result = {"BUSY_" + match[1].str(), std::stoi(match[1])};
    return true;
  }
  return false;
}
}  // namespace pharmacy
