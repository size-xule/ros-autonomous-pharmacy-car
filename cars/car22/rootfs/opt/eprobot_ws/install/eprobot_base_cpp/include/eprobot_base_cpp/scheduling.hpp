#pragma once

#include <optional>

namespace eprobot_base {

// Returns the next deadline when now is due, otherwise nullopt. If the loop
// is more than one whole period late, re-phase from now instead of emitting a
// catch-up burst.
std::optional<double> next_deadline_if_due(double now, double deadline,
                                           double period, double tolerance);

}  // namespace eprobot_base
