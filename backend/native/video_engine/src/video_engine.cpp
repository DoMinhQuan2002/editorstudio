#include "video_engine.h"

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/error.h>
#include <libavutil/imgutils.h>
#include <libavutil/mem.h>
#include <libswscale/swscale.h>
}

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <limits>
#include <list>
#include <memory>
#include <mutex>
#include <new>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

constexpr size_t kFrameCacheLimit = 128U * 1024U * 1024U;
constexpr int kMaxFrameDimension = 8192;

struct CachedFrame {
    std::string key;
    int width{};
    int height{};
    std::vector<uint8_t> rgba;
};

class FrameCache {
public:
    int copy(const std::string& key,
             uint8_t* destination,
             size_t destination_capacity,
             size_t* required_capacity,
             int* output_width,
             int* output_height) {
        std::lock_guard lock(mutex_);
        const auto found = index_.find(key);
        if (found == index_.end()) {
            return -1;
        }
        entries_.splice(entries_.begin(), entries_, found->second);
        const auto& frame = entries_.front();
        if (required_capacity) {
            *required_capacity = frame.rgba.size();
        }
        if (output_width) {
            *output_width = frame.width;
        }
        if (output_height) {
            *output_height = frame.height;
        }
        if (!destination || destination_capacity < frame.rgba.size()) {
            return 1;
        }
        std::memcpy(destination, frame.rgba.data(), frame.rgba.size());
        return 0;
    }

    void put(CachedFrame frame) {
        if (frame.rgba.empty() || frame.rgba.size() > kFrameCacheLimit) {
            return;
        }
        std::lock_guard lock(mutex_);
        if (const auto existing = index_.find(frame.key); existing != index_.end()) {
            bytes_ -= existing->second->rgba.size();
            entries_.erase(existing->second);
            index_.erase(existing);
        }
        bytes_ += frame.rgba.size();
        entries_.push_front(std::move(frame));
        index_[entries_.front().key] = entries_.begin();
        while (bytes_ > kFrameCacheLimit && !entries_.empty()) {
            bytes_ -= entries_.back().rgba.size();
            index_.erase(entries_.back().key);
            entries_.pop_back();
        }
    }

    void clear() {
        std::lock_guard lock(mutex_);
        entries_.clear();
        index_.clear();
        bytes_ = 0;
    }

private:
    std::mutex mutex_;
    std::list<CachedFrame> entries_;
    std::unordered_map<std::string, std::list<CachedFrame>::iterator> index_;
    size_t bytes_{};
};

FrameCache g_frame_cache;
std::once_flag g_ffmpeg_init;

void initialize_ffmpeg() {
    std::call_once(g_ffmpeg_init, [] {
        avformat_network_init();
        av_log_set_level(AV_LOG_ERROR);
    });
}

void set_error(char* destination, size_t capacity, const std::string& message) {
    if (!destination || capacity == 0) {
        return;
    }
    const size_t count = std::min(capacity - 1, message.size());
    std::memcpy(destination, message.data(), count);
    destination[count] = '\0';
}

std::string av_error(int code) {
    std::array<char, AV_ERROR_MAX_STRING_SIZE> buffer{};
    av_strerror(code, buffer.data(), buffer.size());
    return buffer.data();
}

bool wide_to_utf8(const wchar_t* input, std::string& output) {
    if (!input || *input == L'\0') {
        return false;
    }
    const int required = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, input, -1,
                                              nullptr, 0, nullptr, nullptr);
    if (required <= 1) {
        return false;
    }
    output.resize(static_cast<size_t>(required));
    const int converted = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, input, -1,
                                               output.data(), required, nullptr, nullptr);
    if (converted <= 0) {
        output.clear();
        return false;
    }
    output.pop_back();
    return true;
}

std::string cache_key(const std::string& path, int64_t timestamp, int timebase,
                      int max_width, int max_height) {
    return path + '\n' + std::to_string(timestamp) + '/' + std::to_string(timebase) + '\n' +
           std::to_string(max_width) + 'x' + std::to_string(max_height);
}

struct FormatContext {
    AVFormatContext* value{};
    ~FormatContext() { avformat_close_input(&value); }
};

struct CodecContext {
    AVCodecContext* value{};
    ~CodecContext() { avcodec_free_context(&value); }
};

struct Frame {
    AVFrame* value{av_frame_alloc()};
    ~Frame() { av_frame_free(&value); }
};

struct Packet {
    AVPacket* value{av_packet_alloc()};
    ~Packet() { av_packet_free(&value); }
};

int open_input(const std::string& path, FormatContext& format, char* error, size_t error_capacity) {
    initialize_ffmpeg();
    int result = avformat_open_input(&format.value, path.c_str(), nullptr, nullptr);
    if (result < 0) {
        set_error(error, error_capacity, "Không mở được media: " + av_error(result));
        return -1;
    }
    result = avformat_find_stream_info(format.value, nullptr);
    if (result < 0) {
        set_error(error, error_capacity, "Không đọc được thông tin stream: " + av_error(result));
        return -1;
    }
    return 0;
}

int scale_frame_to_packed_32bit(const AVFrame* source,
                                int width,
                                int height,
                                AVPixelFormat destination_format,
                                std::vector<uint8_t>& output,
                                char* error,
                                size_t error_capacity) {
    if (!source || source->width <= 0 || source->height <= 0 ||
        !source->data[0] || source->linesize[0] == 0 ||
        width <= 0 || height <= 0 ||
        width > kMaxFrameDimension || height > kMaxFrameDimension ||
        width > std::numeric_limits<int>::max() / 4) {
        set_error(error, error_capacity, "Kích thước hoặc stride frame RGBA/BGRA không hợp lệ.");
        return -1;
    }

    const size_t row_bytes = static_cast<size_t>(width) * 4U;
    const size_t max_size = std::numeric_limits<size_t>::max();
    if (static_cast<size_t>(height) > max_size / row_bytes) {
        set_error(error, error_capacity, "Kích thước frame RGBA/BGRA bị tràn số.");
        return -1;
    }
    const size_t packed_bytes = row_bytes * static_cast<size_t>(height);
    if (packed_bytes > kFrameCacheLimit ||
        packed_bytes > max_size - AV_INPUT_BUFFER_PADDING_SIZE ||
        packed_bytes > output.max_size()) {
        set_error(error, error_capacity, "Frame RGBA/BGRA vượt giới hạn kích thước hỗ trợ.");
        return -1;
    }

    std::unique_ptr<SwsContext, decltype(&sws_freeContext)> scaler(
        sws_getContext(source->width, source->height,
                       static_cast<AVPixelFormat>(source->format),
                       width, height, destination_format,
                       SWS_BICUBIC, nullptr, nullptr, nullptr),
        &sws_freeContext);
    if (!scaler) {
        set_error(error, error_capacity, "Không tạo được bộ chuyển đổi pixel RGBA/BGRA.");
        return -1;
    }

    // swscale's optimized conversion paths may touch padding at the end of the
    // destination plane. Keep that padding outside the tightly packed frame
    // returned to Python so it cannot corrupt the process heap.
    std::unique_ptr<uint8_t, decltype(&av_free)> padded_destination(
        static_cast<uint8_t*>(av_mallocz(packed_bytes + AV_INPUT_BUFFER_PADDING_SIZE)), &av_free);
    if (!padded_destination) {
        set_error(error, error_capacity, "Không đủ bộ nhớ cho frame RGBA/BGRA đệm.");
        return -1;
    }

    uint8_t* destination_data[4] = {padded_destination.get(), nullptr, nullptr, nullptr};
    int destination_stride[4] = {static_cast<int>(row_bytes), 0, 0, 0};
    if (destination_stride[0] <= 0 ||
        static_cast<size_t>(destination_stride[0]) < row_bytes) {
        set_error(error, error_capacity, "Stride đích RGBA/BGRA nhỏ hơn một hàng pixel.");
        return -1;
    }
    const int scaled_rows = sws_scale(scaler.get(), source->data, source->linesize,
                                      0, source->height, destination_data, destination_stride);
    if (scaled_rows != height) {
        set_error(error, error_capacity, "Không chuyển đổi đầy đủ frame sang RGBA/BGRA.");
        return -1;
    }

    try {
        output.resize(packed_bytes);
    } catch (const std::bad_alloc&) {
        set_error(error, error_capacity, "Không đủ bộ nhớ cho frame RGBA/BGRA.");
        return -1;
    } catch (const std::length_error&) {
        set_error(error, error_capacity, "Frame RGBA/BGRA vượt giới hạn vector.");
        return -1;
    }
    for (int row = 0; row < height; ++row) {
        std::memcpy(output.data() + static_cast<size_t>(row) * row_bytes,
                    destination_data[0] + static_cast<size_t>(row) * destination_stride[0], row_bytes);
    }
    return 0;
}

int decode_frame(const std::string& path,
                 int64_t timestamp,
                 int timebase,
                 int max_width,
                 int max_height,
                 CachedFrame& output,
                 char* error,
                 size_t error_capacity) {
    FormatContext format;
    if (open_input(path, format, error, error_capacity) != 0) {
        return -1;
    }

    const int video_index = av_find_best_stream(format.value, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
    if (video_index < 0) {
        set_error(error, error_capacity, "Tệp không có luồng video có thể giải mã.");
        return -1;
    }
    AVStream* stream = format.value->streams[video_index];
    const AVCodec* decoder = avcodec_find_decoder(stream->codecpar->codec_id);
    if (!decoder) {
        set_error(error, error_capacity, "Không tìm thấy bộ giải mã cho codec video.");
        return -1;
    }

    CodecContext codec;
    codec.value = avcodec_alloc_context3(decoder);
    if (!codec.value) {
        set_error(error, error_capacity, "Không đủ bộ nhớ để tạo bộ giải mã video.");
        return -1;
    }
    int result = avcodec_parameters_to_context(codec.value, stream->codecpar);
    if (result < 0 || (result = avcodec_open2(codec.value, decoder, nullptr)) < 0) {
        set_error(error, error_capacity, "Không khởi tạo được bộ giải mã: " + av_error(result));
        return -1;
    }

    const AVRational timestamp_base{1, timebase};
    const int64_t relative_target = av_rescale_q(timestamp, timestamp_base, stream->time_base);
    const int64_t target = stream->start_time == AV_NOPTS_VALUE ? relative_target : relative_target + stream->start_time;
    result = av_seek_frame(format.value, video_index, target, AVSEEK_FLAG_BACKWARD);
    if (result < 0) {
        // Some demuxers do not support stream-index seeking. Fall back to the
        // container time base and decode forward from the nearest keyframe.
        const int64_t container_target = av_rescale_q(timestamp, timestamp_base, AV_TIME_BASE_Q);
        result = av_seek_frame(format.value, -1, container_target, AVSEEK_FLAG_BACKWARD);
        if (result < 0) {
            av_seek_frame(format.value, video_index, 0, AVSEEK_FLAG_BACKWARD);
        }
    }
    avcodec_flush_buffers(codec.value);

    Frame decoded;
    Frame selected;
    Packet packet;
    if (!decoded.value || !selected.value || !packet.value) {
        set_error(error, error_capacity, "Không đủ bộ nhớ để giải mã frame.");
        return -1;
    }
    bool found_at_or_after = false;
    auto drain_decoder = [&]() -> int {
        while (true) {
            const int receive_result = avcodec_receive_frame(codec.value, decoded.value);
            if (receive_result == AVERROR(EAGAIN) || receive_result == AVERROR_EOF) {
                return 0;
            }
            if (receive_result < 0) {
                return receive_result;
            }
            int64_t pts = decoded.value->best_effort_timestamp;
            if (pts == AV_NOPTS_VALUE) {
                pts = decoded.value->pts;
            }
            av_frame_unref(selected.value);
            if (av_frame_ref(selected.value, decoded.value) < 0) {
                av_frame_unref(decoded.value);
                return AVERROR(ENOMEM);
            }
            av_frame_unref(decoded.value);
            if (pts != AV_NOPTS_VALUE && pts >= target) {
                found_at_or_after = true;
                return 0;
            }
        }
    };

    while (!found_at_or_after && (result = av_read_frame(format.value, packet.value)) >= 0) {
        if (packet.value->stream_index == video_index) {
            const int send_result = avcodec_send_packet(codec.value, packet.value);
            if (send_result < 0 && send_result != AVERROR(EAGAIN)) {
                av_packet_unref(packet.value);
                set_error(error, error_capacity, "Lỗi gửi packet cho bộ giải mã: " + av_error(send_result));
                return -1;
            }
            const int drain_result = drain_decoder();
            if (drain_result < 0) {
                av_packet_unref(packet.value);
                set_error(error, error_capacity, "Lỗi giải mã frame: " + av_error(drain_result));
                return -1;
            }
        }
        av_packet_unref(packet.value);
    }
    if (!found_at_or_after) {
        const int flush_result = avcodec_send_packet(codec.value, nullptr);
        if (flush_result >= 0 || flush_result == AVERROR_EOF) {
            const int drain_result = drain_decoder();
            if (drain_result < 0) {
                set_error(error, error_capacity, "Lỗi hoàn tất giải mã frame: " + av_error(drain_result));
                return -1;
            }
        }
    }
    if (selected.value->width <= 0 || selected.value->height <= 0) {
        set_error(error, error_capacity, "Không giải mã được frame tại vị trí yêu cầu.");
        return -1;
    }

    const double scale = std::min({1.0,
        static_cast<double>(max_width) / selected.value->width,
        static_cast<double>(max_height) / selected.value->height});
    const int width = std::max(1, static_cast<int>(std::lround(selected.value->width * scale)));
    const int height = std::max(1, static_cast<int>(std::lround(selected.value->height * scale)));
    const size_t bytes = static_cast<size_t>(width) * static_cast<size_t>(height) * 4U;
    if (bytes > kFrameCacheLimit) {
        set_error(error, error_capacity, "Frame sau giải mã vượt giới hạn bộ nhớ cache.");
        return -1;
    }

    output.width = width;
    output.height = height;
    if (scale_frame_to_packed_32bit(selected.value, width, height, AV_PIX_FMT_RGBA,
                                    output.rgba, error, error_capacity) != 0) {
        return -1;
    }
    return 0;
}

class DecoderSession {
public:
    ~DecoderSession() {
        av_packet_free(&packet_);
        av_frame_free(&current_);
        av_frame_free(&scratch_);
        avcodec_free_context(&codec_);
        avformat_close_input(&format_);
    }

    int open(const std::string& path, char* error, size_t error_capacity) {
        initialize_ffmpeg();
        int result = avformat_open_input(&format_, path.c_str(), nullptr, nullptr);
        if (result < 0) {
            set_error(error, error_capacity, "Không mở được media: " + av_error(result));
            return -1;
        }
        result = avformat_find_stream_info(format_, nullptr);
        if (result < 0) {
            set_error(error, error_capacity, "Không đọc được thông tin stream: " + av_error(result));
            return -1;
        }
        stream_index_ = av_find_best_stream(format_, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
        if (stream_index_ < 0) {
            set_error(error, error_capacity, "Tệp không có luồng video có thể giải mã.");
            return -1;
        }
        stream_ = format_->streams[stream_index_];
        const AVCodec* decoder = avcodec_find_decoder(stream_->codecpar->codec_id);
        if (!decoder) {
            set_error(error, error_capacity, "Không tìm thấy bộ giải mã cho codec video.");
            return -1;
        }
        codec_ = avcodec_alloc_context3(decoder);
        if (!codec_) {
            set_error(error, error_capacity, "Không đủ bộ nhớ để tạo bộ giải mã video.");
            return -1;
        }
        result = avcodec_parameters_to_context(codec_, stream_->codecpar);
        if (result < 0 || (result = avcodec_open2(codec_, decoder, nullptr)) < 0) {
            set_error(error, error_capacity, "Không khởi tạo được bộ giải mã: " + av_error(result));
            return -1;
        }
        current_ = av_frame_alloc();
        scratch_ = av_frame_alloc();
        packet_ = av_packet_alloc();
        if (!current_ || !scratch_ || !packet_) {
            set_error(error, error_capacity, "Không đủ bộ nhớ để tạo phiên giải mã.");
            return -1;
        }
        return 0;
    }

    int decode_bgra(int64_t timestamp_ms, int max_width, int max_height,
                    uint8_t* destination, size_t destination_capacity,
                    size_t* required_capacity, int* output_width, int* output_height,
                    char* error, size_t error_capacity) {
        std::lock_guard lock(mutex_);
        if (timestamp_ms < 0 || max_width < 1 || max_height < 1 ||
            max_width > kMaxFrameDimension || max_height > kMaxFrameDimension) {
            set_error(error, error_capacity, "Thời gian hoặc kích thước frame không hợp lệ.");
            return -1;
        }
        const std::string requested_key = std::to_string(timestamp_ms) + ':' +
            std::to_string(max_width) + 'x' + std::to_string(max_height);
        if (requested_key != cached_key_) {
            const int64_t relative_target = av_rescale_q(timestamp_ms, AVRational{1, 1000}, stream_->time_base);
            const int64_t target = stream_->start_time == AV_NOPTS_VALUE ? relative_target : relative_target + stream_->start_time;
            if (!has_current_ || (current_pts_ != AV_NOPTS_VALUE && target < current_pts_)) {
                if (seek_to(timestamp_ms, error, error_capacity) != 0) return -1;
            }
            if (!has_current_ || current_pts_ == AV_NOPTS_VALUE || current_pts_ < target) {
                if (decode_at_or_after(target, error, error_capacity) != 0) return -1;
            }
            if (convert_current_to_bgra(max_width, max_height, error, error_capacity) != 0) return -1;
            cached_key_ = requested_key;
        }
        if (required_capacity) *required_capacity = output_.size();
        if (output_width) *output_width = output_width_;
        if (output_height) *output_height = output_height_;
        if (!destination || destination_capacity < output_.size()) return 1;
        std::memcpy(destination, output_.data(), output_.size());
        return 0;
    }

private:
    int seek_to(int64_t timestamp_ms, char* error, size_t error_capacity) {
        const int64_t relative_target = av_rescale_q(timestamp_ms, AVRational{1, 1000}, stream_->time_base);
        const int64_t target = stream_->start_time == AV_NOPTS_VALUE ? relative_target : relative_target + stream_->start_time;
        int result = av_seek_frame(format_, stream_index_, target, AVSEEK_FLAG_BACKWARD);
        if (result < 0) {
            const int64_t container_target = av_rescale_q(timestamp_ms, AVRational{1, 1000}, AV_TIME_BASE_Q);
            result = av_seek_frame(format_, -1, container_target, AVSEEK_FLAG_BACKWARD);
            if (result < 0) result = av_seek_frame(format_, stream_index_, 0, AVSEEK_FLAG_BACKWARD);
        }
        if (result < 0) {
            set_error(error, error_capacity, "Không tua được đến frame cần xem: " + av_error(result));
            return -1;
        }
        avcodec_flush_buffers(codec_);
        av_frame_unref(current_);
        av_frame_unref(scratch_);
        current_pts_ = AV_NOPTS_VALUE;
        has_current_ = false;
        eof_ = false;
        cached_key_.clear();
        return 0;
    }

    int decode_at_or_after(int64_t target, char* error, size_t error_capacity) {
        while (true) {
            int result = avcodec_receive_frame(codec_, scratch_);
            if (result == AVERROR(EAGAIN)) {
                if (eof_) {
                    if (has_current_) return 0;
                    set_error(error, error_capacity, "Không còn frame video tại thời gian yêu cầu.");
                    return -1;
                }
                result = av_read_frame(format_, packet_);
                if (result < 0) {
                    eof_ = true;
                    result = avcodec_send_packet(codec_, nullptr);
                    if (result < 0 && result != AVERROR_EOF) {
                        set_error(error, error_capacity, "Lỗi hoàn tất giải mã frame: " + av_error(result));
                        return -1;
                    }
                    continue;
                }
                if (packet_->stream_index == stream_index_) {
                    result = avcodec_send_packet(codec_, packet_);
                    if (result < 0 && result != AVERROR(EAGAIN) && result != AVERROR_EOF) {
                        av_packet_unref(packet_);
                        set_error(error, error_capacity, "Lỗi gửi packet cho bộ giải mã: " + av_error(result));
                        return -1;
                    }
                }
                av_packet_unref(packet_);
                continue;
            }
            if (result == AVERROR_EOF) {
                if (has_current_) return 0;
                set_error(error, error_capacity, "Không còn frame video tại thời gian yêu cầu.");
                return -1;
            }
            if (result < 0) {
                set_error(error, error_capacity, "Lỗi giải mã frame: " + av_error(result));
                return -1;
            }
            int64_t pts = scratch_->best_effort_timestamp;
            if (pts == AV_NOPTS_VALUE) pts = scratch_->pts;
            const bool found = pts == AV_NOPTS_VALUE || pts >= target;
            av_frame_unref(current_);
            if (av_frame_ref(current_, scratch_) < 0) {
                av_frame_unref(scratch_);
                set_error(error, error_capacity, "Không đủ bộ nhớ để giữ frame xem trước.");
                return -1;
            }
            av_frame_unref(scratch_);
            current_pts_ = pts;
            has_current_ = true;
            if (found) return 0;
        }
    }

    int convert_current_to_bgra(int max_width, int max_height, char* error, size_t error_capacity) {
        const double scale = std::min({1.0,
            static_cast<double>(max_width) / current_->width,
            static_cast<double>(max_height) / current_->height});
        const int width = std::max(1, static_cast<int>(std::lround(current_->width * scale)));
        const int height = std::max(1, static_cast<int>(std::lround(current_->height * scale)));
        const size_t bytes = static_cast<size_t>(width) * static_cast<size_t>(height) * 4U;
        if (bytes > kFrameCacheLimit) {
            set_error(error, error_capacity, "Frame sau giải mã vượt giới hạn bộ nhớ preview.");
            return -1;
        }
        if (scale_frame_to_packed_32bit(current_, width, height, AV_PIX_FMT_BGRA,
                                        output_, error, error_capacity) != 0) {
            return -1;
        }
        output_width_ = width;
        output_height_ = height;
        return 0;
    }

    std::mutex mutex_;
    AVFormatContext* format_{};
    AVCodecContext* codec_{};
    AVStream* stream_{};
    AVFrame* current_{};
    AVFrame* scratch_{};
    AVPacket* packet_{};
    int stream_index_{-1};
    int64_t current_pts_{AV_NOPTS_VALUE};
    bool has_current_{};
    bool eof_{};
    std::string cached_key_;
    std::vector<uint8_t> output_;
    int output_width_{};
    int output_height_{};
};

struct Pixel {
    double b{};
    double g{};
    double r{};
    double a{};
};

Pixel sample_bgra(const MSVE_PreviewLayer& layer, double x, double y) {
    const int x0 = static_cast<int>(std::floor(x));
    const int y0 = static_cast<int>(std::floor(y));
    const double fx = x - x0;
    const double fy = y - y0;
    Pixel result{};
    for (int dy = 0; dy <= 1; ++dy) {
        const int sy = std::clamp(y0 + dy, 0, layer.height - 1);
        const double wy = dy == 0 ? 1.0 - fy : fy;
        for (int dx = 0; dx <= 1; ++dx) {
            const int sx = std::clamp(x0 + dx, 0, layer.width - 1);
            const double wx = dx == 0 ? 1.0 - fx : fx;
            const double weight = wx * wy;
            const uint8_t* pixel = layer.pixels + static_cast<size_t>(sy) * layer.stride + static_cast<size_t>(sx) * 4U;
            result.b += pixel[0] * weight;
            result.g += pixel[1] * weight;
            result.r += pixel[2] * weight;
            result.a += pixel[3] * weight;
        }
    }
    return result;
}

void composite_layer(const MSVE_PreviewLayer& layer, int canvas_width, int canvas_height, uint8_t* canvas) {
    if (!layer.pixels || layer.width <= 0 || layer.height <= 0 || layer.stride < layer.width * 4 ||
        layer.opacity <= 0 || layer.scale <= 0) return;
    const double fit_x = static_cast<double>(canvas_width) / layer.width;
    const double fit_y = static_cast<double>(canvas_height) / layer.height;
    const double fit = layer.fit_mode == 1 ? std::max(fit_x, fit_y) : std::min(fit_x, fit_y);
    const double radians = layer.rotation_degrees * 3.14159265358979323846 / 180.0;
    const double cos_angle = std::cos(radians);
    const double sin_angle = std::sin(radians);
    const double center_x = canvas_width * (0.5 + layer.position_x);
    const double center_y = canvas_height * (0.5 + layer.position_y);
    const double output_alpha = std::clamp(layer.opacity, 0.0, 1.0);
    const double destination_width = layer.width * fit * layer.scale;
    const double destination_height = layer.height * fit * layer.scale;
    const double radius = std::sqrt(destination_width * destination_width + destination_height * destination_height) * 0.5;
    const int left = std::max(0, static_cast<int>(std::floor(center_x - radius)));
    const int right = std::min(canvas_width - 1, static_cast<int>(std::ceil(center_x + radius)));
    const int top = std::max(0, static_cast<int>(std::floor(center_y - radius)));
    const int bottom = std::min(canvas_height - 1, static_cast<int>(std::ceil(center_y + radius)));
    if (left > right || top > bottom) return;

    for (int y = top; y <= bottom; ++y) {
        for (int x = left; x <= right; ++x) {
            const double dx = x + 0.5 - center_x;
            const double dy = y + 0.5 - center_y;
            const double unrotated_x = cos_angle * dx + sin_angle * dy;
            const double unrotated_y = -sin_angle * dx + cos_angle * dy;
            const double local_x = unrotated_x / layer.scale;
            const double local_y = unrotated_y / layer.scale;
            // The layer center has already been applied through center_x/center_y.
            // Map the inverse-transformed point around the source image center;
            // using the canvas center here offsets/crops portrait clips whenever
            // the fitted source dimensions differ from the canvas dimensions.
            const double source_x = local_x / fit + layer.width * 0.5;
            const double source_y = local_y / fit + layer.height * 0.5;
            if (source_x < 0 || source_y < 0 || source_x >= layer.width || source_y >= layer.height) continue;
            Pixel source = sample_bgra(layer, source_x, source_y);
            if (layer.effect == 1) { // warm
                source.r += 20.4;
                source.g += 5.1;
                source.b -= 20.4;
            } else if (layer.effect == 2) { // mono
                const double luminance = source.r * 0.2126 + source.g * 0.7152 + source.b * 0.0722;
                source.r = source.g = source.b = luminance;
            } else if (layer.effect == 3) { // vivid
                const double luminance = source.r * 0.2126 + source.g * 0.7152 + source.b * 0.0722;
                source.r = (luminance + (source.r - luminance) * 1.18 - 128.0) * 1.08 + 128.0;
                source.g = (luminance + (source.g - luminance) * 1.18 - 128.0) * 1.08 + 128.0;
                source.b = (luminance + (source.b - luminance) * 1.18 - 128.0) * 1.08 + 128.0;
            }
            source.r = std::clamp(source.r, 0.0, 255.0);
            source.g = std::clamp(source.g, 0.0, 255.0);
            source.b = std::clamp(source.b, 0.0, 255.0);
            const double alpha = std::clamp(source.a / 255.0 * output_alpha, 0.0, 1.0);
            if (alpha <= 0) continue;
            uint8_t* target = canvas + (static_cast<size_t>(y) * canvas_width + x) * 4U;
            const double color_multiplier = layer.premultiplied_alpha ? output_alpha : alpha;
            target[0] = static_cast<uint8_t>(std::clamp(source.b * color_multiplier + target[0] * (1.0 - alpha), 0.0, 255.0));
            target[1] = static_cast<uint8_t>(std::clamp(source.g * color_multiplier + target[1] * (1.0 - alpha), 0.0, 255.0));
            target[2] = static_cast<uint8_t>(std::clamp(source.r * color_multiplier + target[2] * (1.0 - alpha), 0.0, 255.0));
            target[3] = static_cast<uint8_t>(std::clamp(alpha * 255.0 + target[3] * (1.0 - alpha), 0.0, 255.0));
        }
    }
}

} // namespace

int msve_probe(const wchar_t* input_path, MSVE_MediaInfo* info, char* error_buffer, size_t error_capacity) {
    if (!info) {
        set_error(error_buffer, error_capacity, "Thiếu vùng nhận kết quả metadata.");
        return -1;
    }
    std::string path;
    if (!wide_to_utf8(input_path, path)) {
        set_error(error_buffer, error_capacity, "Đường dẫn media không hợp lệ.");
        return -1;
    }
    FormatContext format;
    if (open_input(path, format, error_buffer, error_capacity) != 0) {
        return -1;
    }

    std::memset(info, 0, sizeof(*info));
    info->duration_ms = -1;
    if (format.value->duration != AV_NOPTS_VALUE && format.value->duration >= 0) {
        info->duration_ms = av_rescale_q(format.value->duration, AV_TIME_BASE_Q, AVRational{1, 1000});
    }
    for (unsigned int index = 0; index < format.value->nb_streams; ++index) {
        const AVStream* stream = format.value->streams[index];
        const AVCodecParameters* parameters = stream->codecpar;
        if (parameters->codec_type == AVMEDIA_TYPE_VIDEO && !info->has_video) {
            info->has_video = 1;
            info->width = parameters->width;
            info->height = parameters->height;
            strncpy_s(info->video_codec, sizeof(info->video_codec),
                      parameters->codec_id == AV_CODEC_ID_NONE ? "unknown" : avcodec_get_name(parameters->codec_id),
                      _TRUNCATE);
        } else if (parameters->codec_type == AVMEDIA_TYPE_AUDIO && !info->has_audio) {
            info->has_audio = 1;
            strncpy_s(info->audio_codec, sizeof(info->audio_codec),
                      parameters->codec_id == AV_CODEC_ID_NONE ? "unknown" : avcodec_get_name(parameters->codec_id),
                      _TRUNCATE);
        }
    }
    if (!info->has_video && !info->has_audio) {
        set_error(error_buffer, error_capacity, "Media không chứa luồng video hoặc âm thanh.");
        return -1;
    }
    return 0;
}

namespace {

int decode_frame_rgba_in_timebase(const wchar_t* input_path,
                                  int64_t timestamp,
                                  int timebase,
                                  int max_width,
                                  int max_height,
                                  uint8_t* destination,
                                  size_t destination_capacity,
                                  size_t* required_capacity,
                                  int* output_width,
                                  int* output_height,
                                  char* error_buffer,
                                  size_t error_capacity) {
    if (timestamp < 0 || timebase < 1 || timebase > 1'000'000'000 ||
        max_width < 1 || max_height < 1 ||
        max_width > kMaxFrameDimension || max_height > kMaxFrameDimension) {
        set_error(error_buffer, error_capacity, "Timestamp/timebase hoặc kích thước frame không hợp lệ.");
        return -1;
    }
    std::string path;
    if (!wide_to_utf8(input_path, path)) {
        set_error(error_buffer, error_capacity, "Đường dẫn media không hợp lệ.");
        return -1;
    }
    const std::string key = cache_key(path, timestamp, timebase, max_width, max_height);
    const int cached_result = g_frame_cache.copy(key, destination, destination_capacity,
                                                  required_capacity, output_width, output_height);
    if (cached_result >= 0) {
        return cached_result;
    }
    CachedFrame frame;
    if (decode_frame(path, timestamp, timebase, max_width, max_height,
                     frame, error_buffer, error_capacity) != 0) {
        return -1;
    }
    frame.key = key;
    g_frame_cache.put(std::move(frame));
    return g_frame_cache.copy(key, destination, destination_capacity, required_capacity,
                              output_width, output_height);
}

} // namespace

int msve_decode_frame_rgba(const wchar_t* input_path,
                           int64_t timestamp_ms,
                           int max_width,
                           int max_height,
                           uint8_t* destination,
                           size_t destination_capacity,
                           size_t* required_capacity,
                           int* output_width,
                           int* output_height,
                           char* error_buffer,
                           size_t error_capacity) {
    return decode_frame_rgba_in_timebase(input_path, timestamp_ms, 1000, max_width, max_height,
        destination, destination_capacity, required_capacity, output_width, output_height,
        error_buffer, error_capacity);
}

int msve_decode_frame_rgba_ticks(const wchar_t* input_path,
                                 int64_t timestamp_ticks,
                                 int timebase,
                                 int max_width,
                                 int max_height,
                                 uint8_t* destination,
                                 size_t destination_capacity,
                                 size_t* required_capacity,
                                 int* output_width,
                                 int* output_height,
                                 char* error_buffer,
                                 size_t error_capacity) {
    return decode_frame_rgba_in_timebase(input_path, timestamp_ticks, timebase,
        max_width, max_height, destination, destination_capacity, required_capacity,
        output_width, output_height, error_buffer, error_capacity);
}

void* msve_decoder_open(const wchar_t* input_path, char* error_buffer, size_t error_capacity) {
    std::string path;
    if (!wide_to_utf8(input_path, path)) {
        set_error(error_buffer, error_capacity, "Đường dẫn media không hợp lệ.");
        return nullptr;
    }
    auto decoder = std::make_unique<DecoderSession>();
    if (decoder->open(path, error_buffer, error_capacity) != 0) return nullptr;
    return decoder.release();
}

int msve_decoder_decode_bgra(void* decoder,
                             int64_t timestamp_ms,
                             int max_width,
                             int max_height,
                             uint8_t* destination,
                             size_t destination_capacity,
                             size_t* required_capacity,
                             int* output_width,
                             int* output_height,
                             char* error_buffer,
                             size_t error_capacity) {
    if (!decoder) {
        set_error(error_buffer, error_capacity, "Phiên giải mã không hợp lệ.");
        return -1;
    }
    return static_cast<DecoderSession*>(decoder)->decode_bgra(timestamp_ms, max_width, max_height,
        destination, destination_capacity, required_capacity, output_width, output_height,
        error_buffer, error_capacity);
}

void msve_decoder_close(void* decoder) {
    delete static_cast<DecoderSession*>(decoder);
}

int msve_compose_preview_bgra(int canvas_width,
                              int canvas_height,
                              const MSVE_PreviewLayer* layers,
                              int layer_count,
                              uint8_t* destination,
                              size_t destination_capacity,
                              char* error_buffer,
                              size_t error_capacity) {
    if (canvas_width < 1 || canvas_height < 1 || canvas_width > 4096 || canvas_height > 4096 ||
        layer_count < 0 || layer_count > 32 || (layer_count > 0 && !layers)) {
        set_error(error_buffer, error_capacity, "Kích thước canvas hoặc số lớp preview không hợp lệ.");
        return -1;
    }
    const size_t required = static_cast<size_t>(canvas_width) * canvas_height * 4U;
    if (required > kFrameCacheLimit) {
        set_error(error_buffer, error_capacity, "Canvas preview vượt giới hạn bộ nhớ.");
        return -1;
    }
    if (!destination || destination_capacity < required) {
        set_error(error_buffer, error_capacity, "Vùng nhận frame preview quá nhỏ.");
        return 1;
    }
    for (size_t offset = 0; offset < required; offset += 4U) {
        destination[offset] = 0;
        destination[offset + 1] = 0;
        destination[offset + 2] = 0;
        destination[offset + 3] = 255;
    }
    for (int index = 0; index < layer_count; ++index) {
        const auto& layer = layers[index];
        if (layer.width < 1 || layer.height < 1 || layer.width > kMaxFrameDimension ||
            layer.height > kMaxFrameDimension || layer.stride < layer.width * 4 ||
            layer.fit_mode < 0 || layer.fit_mode > 1 ||
            layer.effect < 0 || layer.effect > 3 ||
            !std::isfinite(layer.position_x) || !std::isfinite(layer.position_y) ||
            !std::isfinite(layer.scale) || !std::isfinite(layer.rotation_degrees) ||
            !std::isfinite(layer.opacity) || layer.scale <= 0) {
            set_error(error_buffer, error_capacity, "Thông số của một lớp preview không hợp lệ.");
            return -1;
        }
        composite_layer(layer, canvas_width, canvas_height, destination);
    }
    return 0;
}

void msve_clear_frame_cache() {
    g_frame_cache.clear();
}

const char* msve_version() {
    return "0.1.0";
}
