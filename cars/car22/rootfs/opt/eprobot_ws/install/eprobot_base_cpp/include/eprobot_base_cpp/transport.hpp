#pragma once

#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace eprobot_base {

class TransportError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

class Transport {
 public:
  virtual ~Transport() = default;
  virtual void open() = 0;
  virtual void close() = 0;
  virtual std::vector<std::uint8_t> read(std::size_t max_bytes = 4096) = 0;
  virtual void write(const std::vector<std::uint8_t>& data) = 0;
  virtual bool is_open() const = 0;
};

class SerialTransport final : public Transport {
 public:
  explicit SerialTransport(std::string port, int baudrate = 115200,
                           double read_timeout = 0.0, double write_timeout = 0.1);
  ~SerialTransport() override;

  void open() override;
  void close() override;
  std::vector<std::uint8_t> read(std::size_t max_bytes = 4096) override;
  void write(const std::vector<std::uint8_t>& data) override;
  bool is_open() const override { return fd_ >= 0; }

 private:
  std::string port_;
  int baudrate_;
  double read_timeout_;
  double write_timeout_;
  int fd_ = -1;
};

class SocketTransport final : public Transport {
 public:
  SocketTransport(std::string host, int port, double connect_timeout = 2.0);
  ~SocketTransport() override;

  void open() override;
  void close() override;
  std::vector<std::uint8_t> read(std::size_t max_bytes = 4096) override;
  void write(const std::vector<std::uint8_t>& data) override;
  bool is_open() const override { return fd_ >= 0; }

 private:
  std::string host_;
  int port_;
  double connect_timeout_;
  int fd_ = -1;
};

class LoopbackTransport final : public Transport {
 public:
  void open() override;
  void close() override;
  std::vector<std::uint8_t> read(std::size_t max_bytes = 4096) override;
  void write(const std::vector<std::uint8_t>& data) override;
  bool is_open() const override { return open_; }

  void feed(const std::uint8_t* data, std::size_t length);
  void feed(const std::vector<std::uint8_t>& data) { feed(data.data(), data.size()); }
  std::vector<std::uint8_t> take_written();
  std::size_t pending_written() const { return tx_.size(); }

  int open_count = 0;
  int close_count = 0;

 private:
  bool open_ = false;
  std::vector<std::uint8_t> rx_;
  std::vector<std::uint8_t> tx_;
};

}  // namespace eprobot_base
