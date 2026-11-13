// mono8_relay: /camera/color/image_raw (rgb8) -> /camera/rgb/image_raw (mono8)
//
// The QR / board-2 binaries hard-code the topic name and the mono8 encoding,
// while Orbbec's driver only offers rgb8 colour, so exactly this conversion has
// to happen somewhere.  C++ keeps the cost near zero: subscribing to 640x480
// rgb8 at ~27 Hz means ~25 MB/s through DDS, which is cheap in C++ and
// expensive in rclpy (the Python version burned 20-30% of a core).
#include <memory>
#include <chrono>

#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/image.hpp"
#include "sensor_msgs/msg/camera_info.hpp"
#include "opencv2/imgproc.hpp"

namespace
{
constexpr char kSrc[] = "/camera/color/image_raw";
constexpr char kDst[] = "/camera/rgb/image_raw";
constexpr char kDstInfo[] = "/camera/rgb/camera_info";
}  // namespace

class Mono8Relay : public rclcpp::Node
{
public:
  Mono8Relay()
  : rclcpp::Node("image_relay")
  {
    // Declared as an integer: `-p max_fps:=10` then works without the caller
    // having to remember a trailing ".0" (rclcpp rejects int->double overrides).
    const int max_fps = this->declare_parameter<int>("max_fps", 10);
    min_period_ = max_fps > 0 ? std::chrono::duration<double>(1.0 / max_fps)
                              : std::chrono::duration<double>(0.0);

    auto best_effort = rclcpp::QoS(rclcpp::KeepLast(1)).best_effort();

    pub_ = this->create_publisher<sensor_msgs::msg::Image>(kDst, best_effort);
    pub_info_ = this->create_publisher<sensor_msgs::msg::CameraInfo>(kDstInfo, best_effort);

    info_sub_ = this->create_subscription<sensor_msgs::msg::CameraInfo>(
      "/camera/color/camera_info", best_effort,
      [this](sensor_msgs::msg::CameraInfo::ConstSharedPtr msg) {pub_info_->publish(*msg);});

    sub_ = this->create_subscription<sensor_msgs::msg::Image>(
      kSrc, best_effort, [this](sensor_msgs::msg::Image::ConstSharedPtr msg) {convert(*msg);});

    RCLCPP_INFO(this->get_logger(), "relay %s -> %s (mono8, max %d fps)", kSrc, kDst, max_fps);
  }

private:
  void convert(const sensor_msgs::msg::Image & in)
  {
    const auto now = std::chrono::steady_clock::now();
    if (min_period_.count() > 0.0 && last_.time_since_epoch().count() != 0 &&
      now - last_ < min_period_)
    {
      return;
    }
    last_ = now;

    const int w = static_cast<int>(in.width);
    const int h = static_cast<int>(in.height);
    if (w <= 0 || h <= 0 || in.data.empty()) {
      return;
    }

    cv::Mat src(h, w, CV_8UC3, const_cast<uint8_t *>(in.data.data()), in.step);
    cv::Mat gray(h, w, CV_8UC1);
    if (in.encoding == "rgb8") {
      cv::cvtColor(src, gray, cv::COLOR_RGB2GRAY);
    } else if (in.encoding == "bgr8") {
      cv::cvtColor(src, gray, cv::COLOR_BGR2GRAY);
    } else if (in.encoding == "mono8") {
      gray = src.clone();
    } else {
      RCLCPP_WARN_THROTTLE(
        this->get_logger(), *this->get_clock(), 5000,
        "unsupported encoding '%s'", in.encoding.c_str());
      return;
    }

    sensor_msgs::msg::Image out;
    out.header = in.header;
    out.height = in.height;
    out.width = in.width;
    out.encoding = "mono8";
    out.is_bigendian = 0;
    out.step = in.width;
    out.data.assign(gray.data, gray.data + gray.total());
    pub_->publish(out);
  }

  std::chrono::duration<double> min_period_{0.0};
  std::chrono::steady_clock::time_point last_{};
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr pub_info_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr sub_;
  rclcpp::Subscription<sensor_msgs::msg::CameraInfo>::SharedPtr info_sub_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<Mono8Relay>());
  rclcpp::shutdown();
  return 0;
}