cmake_minimum_required(VERSION 3.10)
project(mono8_relay CXX)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -O2)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgproc)

add_executable(mono8_relay src/mono8_relay.cpp)
target_include_directories(mono8_relay PRIVATE
  ${rclcpp_INCLUDE_DIRS} ${sensor_msgs_INCLUDE_DIRS} ${OpenCV_INCLUDE_DIRS})
# This ROS install ships without ament_cmake_target_dependencies, so link the
# imported targets directly instead of using ament_target_dependencies().
target_link_libraries(mono8_relay
  rclcpp::rclcpp
  sensor_msgs::sensor_msgs__rosidl_typesupport_cpp
  ${OpenCV_LIBS})

install(TARGETS mono8_relay DESTINATION lib/${PROJECT_NAME})
ament_package()