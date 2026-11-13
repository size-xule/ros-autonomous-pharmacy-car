#pragma once
#include "pharmacy_pkg/common.hpp"
#include <cstring>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
#include <functional>
#include <thread>
extern char** environ;
namespace pharmacy {
// posix_spawn is safe while ROS callback threads run. Each child has its own
// process group; all descriptors are CLOEXEC, and all protocol I/O is bounded.
class Process {
 public:
  Process()=default;
  Process(const Process&)=delete;
  Process& operator=(const Process&)=delete;
  ~Process(){ stop(); }
  void start(const std::vector<std::string>& args, bool pipes=true, const std::string& error_path="") {
    stop();
    if(args.empty()) throw std::invalid_argument("Empty child command");
    int input[2]={-1,-1}, output[2]={-1,-1};
    if(pipes && (pipe2(input,O_CLOEXEC) || pipe2(output,O_CLOEXEC))) {
      for(int fd: {input[0],input[1],output[0],output[1]}) if(fd>=0) ::close(fd);
      throw std::runtime_error("pipe2 failed");
    }
    posix_spawn_file_actions_t actions; posix_spawn_file_actions_init(&actions);
    if(pipes) {
      posix_spawn_file_actions_adddup2(&actions,input[0],STDIN_FILENO);
      posix_spawn_file_actions_adddup2(&actions,output[1],STDOUT_FILENO);
      for(int fd: {input[0],input[1],output[0],output[1]}) posix_spawn_file_actions_addclose(&actions,fd);
    } else posix_spawn_file_actions_addopen(&actions,STDIN_FILENO,"/dev/null",O_RDONLY,0);
    if(!error_path.empty()) posix_spawn_file_actions_addopen(&actions,STDERR_FILENO,error_path.c_str(),O_WRONLY|O_CREAT|O_APPEND,0600);
    posix_spawnattr_t attr; posix_spawnattr_init(&attr);
    posix_spawnattr_setflags(&attr,POSIX_SPAWN_SETPGROUP); posix_spawnattr_setpgroup(&attr,0);
    std::vector<char*> argv; for(const auto& a:args) argv.push_back(const_cast<char*>(a.c_str())); argv.push_back(nullptr);
    const int error=posix_spawnp(&pid_,argv[0],&actions,&attr,argv.data(),environ);
    posix_spawnattr_destroy(&attr); posix_spawn_file_actions_destroy(&actions);
    if(pipes){ ::close(input[0]); ::close(output[1]); }
    if(error) {
      if(pipes){ ::close(input[1]); ::close(output[0]); }
      pid_=-1; throw std::runtime_error("Cannot start " + args[0] + ": " + std::strerror(error));
    }
    in_=input[1]; out_=output[0]; buffer_.clear();
    if(pipes){ fcntl(in_,F_SETFL,O_NONBLOCK); fcntl(out_,F_SETFL,O_NONBLOCK); }
  }
  bool running() {
    if(pid_<=0) return false;
    int status=0; const pid_t result=waitpid(pid_,&status,WNOHANG);
    if(result==0 || (result<0 && errno==EINTR)) return true;
    exit_code_=result>0 && WIFEXITED(status)?WEXITSTATUS(status):128;
    // Reap the leader and terminate any leftover descendants in its group.
    kill(-pid_,SIGKILL); pid_=-1; return false;
  }
  int exitCode() const {return exit_code_;}
  bool writeAll(const std::string& data, double deadline, const std::function<bool()>& active) {
    size_t offset=0;
    while(offset<data.size() && active() && now()<deadline) {
      if(!waitFd(in_,POLLOUT,deadline)) continue;
      const ssize_t n=::write(in_,data.data()+offset,data.size()-offset);
      if(n>0) offset+=n;
      else if(n<0 && errno!=EAGAIN && errno!=EINTR) return false;
    }
    return offset==data.size();
  }
  bool readLine(std::string& line, double deadline, const std::function<bool()>& active) {
    while(active() && now()<deadline) {
      const auto end=buffer_.find('\n');
      if(end!=std::string::npos){ line=trim(buffer_.substr(0,end)); buffer_.erase(0,end+1); return true; }
      if(buffer_.size()>65536) return false;
      if(!waitFd(out_,POLLIN,deadline)) continue;
      char chunk[4096]; const ssize_t n=::read(out_,chunk,sizeof(chunk));
      if(n>0) buffer_.append(chunk,n);
      else if(n==0 || (n<0 && errno!=EAGAIN && errno!=EINTR)) return false;
    }
    return false;
  }
  void stop() {
    if(in_>=0) ::close(in_);
    if(out_>=0) ::close(out_);
    in_=out_=-1;
    if(pid_>0) {
      kill(-pid_,SIGTERM);
      const double end=now()+0.2;
      while(now()<end && running()) std::this_thread::sleep_for(std::chrono::milliseconds(10));
      if(pid_>0){ kill(-pid_,SIGKILL); while(waitpid(pid_,nullptr,0)<0 && errno==EINTR){} pid_=-1; }
    }
    buffer_.clear();
  }
 private:
  static bool waitFd(int fd, short events, double deadline) {
    if(fd<0) return false;
    pollfd p{fd,events,0};
    int ms=std::max(0,std::min(50,static_cast<int>((deadline-now())*1000)));
    return poll(&p,1,ms)>0 && (p.revents&(events|POLLHUP|POLLERR));
  }
  pid_t pid_=-1; int in_=-1,out_=-1,exit_code_=0; std::string buffer_;
};
}  // namespace pharmacy
