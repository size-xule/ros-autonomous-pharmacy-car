#ifndef PHARMACY_PKG_BOARD_CLASSIFIER_HPP
#define PHARMACY_PKG_BOARD_CLASSIFIER_HPP

#include <opencv2/core.hpp>
#include <string>
#include <vector>

namespace pharmacy_pkg {

struct BoardClassifierConfig {
  int max_image_width = 640;
  bool fast_primary = true;
  double min_primary_score = 0.90;
  double min_score = 0.72;
  double min_margin = 0.10;
  double min_line_score = 0.68;
  double min_character_score = 0.45;
  double min_digit_score = 0.66;
  double max_digit_local_loss = 0.035;
  // Optional full-image template text region. Empty means automatic detection.
  cv::Rect free_template_roi;
  cv::Rect busy_template_roi;
};

struct BoardRecognition {
  std::string label = "UNKNOWN";
  std::string reason = "no_text_pair";
  double score = 0.0;
  double margin = 0.0;
  double free_score = 0.0;
  double busy_score = 0.0;
  double top_score = 0.0;
  double bottom_score = 0.0;
  double min_character_score = 0.0;
  double digit_score = 0.0;
  double digit_context_score = 0.0;
  double elapsed_ms = 0.0;
  cv::Rect roi;
};

// A closed-set recognizer for the two supplied signs, not a general OCR engine.
// Only the two lines of printed text contribute to a decision.
class BoardClassifier {
 public:
  explicit BoardClassifier(const BoardClassifierConfig& config = BoardClassifierConfig());
  bool loadTemplates(const std::string& free_path, const std::string& busy_path,
                     std::string* error = nullptr);
  BoardRecognition recognize(const cv::Mat& image) const;
  bool ready() const { return ready_; }
 private:
  struct TextPair { cv::Mat top; cv::Mat bottom; cv::Rect roi; double quality = 0.0; };
  std::vector<TextPair> extract(const cv::Mat& image, double requested_scale = 0.0) const;
  bool loadTemplate(const std::string& path, const cv::Rect& roi,
                    TextPair* result, std::string* error) const;
  BoardClassifierConfig config_;
  TextPair free_template_;
  TextPair busy_template_;
  bool ready_ = false;
};

}  // namespace pharmacy_pkg
#endif
