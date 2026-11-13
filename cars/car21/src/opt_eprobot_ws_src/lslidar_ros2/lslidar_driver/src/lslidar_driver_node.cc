/*
 * This file is part of lslidar driver.
 *
 * The driver is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * The driver is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with the driver.  If not, see <http://www.gnu.org/licenses/>.
 */

#include "rclcpp/rclcpp.hpp"
#include "lslidar_driver/lslidar_driver.h"

#include <csignal>
#include <cstdlib>

using namespace lslidar_driver;
volatile sig_atomic_t flag = 1;

namespace {
// systemd (KillMode=control-group) and ros2 launch both deliver SIGINT to this
// process, so handle it here with an async-signal-safe flag instead of letting
// rclcpp install its handler.  A second signal arriving mid-shutdown used to
// abort the process with "failed to create guard condition".
volatile sig_atomic_t g_interrupted = 0;
void on_stop_signal(int) { g_interrupted = 1; flag = 0; }
}  // namespace

int main(int argc, char* argv[])
{
  std::signal(SIGINT, on_stop_signal);
  std::signal(SIGTERM, on_stop_signal);
  rclcpp::init(argc, argv, rclcpp::InitOptions(), rclcpp::SignalHandlerOptions::None);
  auto node = std::make_shared<lslidar_driver::LslidarDriver>();
  if (!node->isInitialized()) {
    rclcpp::shutdown();
    return 1;
  }

  while (rclcpp::ok() && !g_interrupted && node->polling()) {
    rclcpp::spin_some(node);
  }
  //rclcpp::spin(node);
  rclcpp::shutdown();
  // The vendor node owns a boost scan thread and DDS threads that do not
  // unwind reliably, which used to leave the process hanging in static
  // destructors until systemd escalated to SIGKILL.  Everything useful is
  // already torn down at this point, so exit without running them.
  std::_Exit(0);
}
