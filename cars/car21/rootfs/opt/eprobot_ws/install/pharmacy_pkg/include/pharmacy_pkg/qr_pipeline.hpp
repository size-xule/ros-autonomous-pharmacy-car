#pragma once
#include <opencv2/core.hpp>
#include <nlohmann/json.hpp>
#include <memory>
#include <set>
#include <string>
#include <vector>

namespace pharmacy { namespace qr {
using Json = nlohmann::json;
struct Candidate {
  std::string text, raw_base64, md5;
  bool invalid=false, inferred=false, decoded=false;
  double x=0, y=0, cx=0, cy=0, w=0, h=0, area=0;
};
struct Detection {
  std::vector<Candidate> grid, candidates;
  Json diagnostics=Json::object();
};
std::string normalizePayload(const std::string& bytes);
std::vector<Candidate> mergeCandidates(std::vector<Candidate> candidates);
std::vector<Candidate> selectGrid(std::vector<Candidate> candidates, cv::Size image);
Json buildResult(const std::vector<Candidate>& grid,
                 const std::set<std::string>& excluded={}, int remaining=3);
std::vector<std::string> signature(const std::vector<Candidate>& grid);
class Decoder {
 public:
  // Optional C ABI defaults to <package>/lib/libpharmacy_qr.so. Environment
  // PHARMACY_QR_LIBRARY and PHARMACY_QR_BACKEND override this value/backend.
  explicit Decoder(const std::string& library="");
  ~Decoder();
  Decoder(const Decoder&)=delete;
  Decoder& operator=(const Decoder&)=delete;
  std::string backend() const;
  std::string nativeError() const;
  Detection detect(const cv::Mat& frame);
 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};
} }
