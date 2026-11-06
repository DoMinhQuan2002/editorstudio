#include "video_engine.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <Windows.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <iomanip>
#include <locale>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct UniqueHandle {
    HANDLE value{INVALID_HANDLE_VALUE};
    ~UniqueHandle() {
        if (value != INVALID_HANDLE_VALUE && value != nullptr) CloseHandle(value);
    }
    UniqueHandle() = default;
    explicit UniqueHandle(HANDLE handle) : value(handle) {}
    UniqueHandle(const UniqueHandle&) = delete;
    UniqueHandle& operator=(const UniqueHandle&) = delete;
    UniqueHandle(UniqueHandle&& other) noexcept : value(other.value) { other.value = INVALID_HANDLE_VALUE; }
    UniqueHandle& operator=(UniqueHandle&& other) noexcept {
        if (this != &other) {
            if (value != INVALID_HANDLE_VALUE && value != nullptr) CloseHandle(value);
            value = other.value;
            other.value = INVALID_HANDLE_VALUE;
        }
        return *this;
    }
    HANDLE get() const { return value; }
};

void set_error(char* destination, size_t capacity, const std::string& message) {
    if (!destination || capacity == 0) return;
    const size_t count = std::min(capacity - 1, message.size());
    std::memcpy(destination, message.data(), count);
    destination[count] = '\0';
}

bool wide_to_utf8(const wchar_t* input, std::string& output) {
    if (!input || *input == L'\0') return false;
    const int required = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, input, -1, nullptr, 0, nullptr, nullptr);
    if (required <= 1) return false;
    output.resize(static_cast<size_t>(required));
    const int converted = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, input, -1,
        output.data(), required, nullptr, nullptr);
    if (converted <= 0) {
        output.clear();
        return false;
    }
    output.resize(static_cast<size_t>(converted - 1));
    return true;
}

bool utf8_to_wide(const std::string& input, std::wstring& output) {
    if (input.empty()) {
        output.clear();
        return true;
    }
    const int required = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, input.c_str(), -1, nullptr, 0);
    if (required <= 0) return false;
    output.resize(static_cast<size_t>(required));
    const int converted = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, input.c_str(), -1,
        output.data(), required);
    if (converted <= 0) {
        output.clear();
        return false;
    }
    output.resize(static_cast<size_t>(converted - 1));
    return true;
}

bool file_exists(const wchar_t* path) {
    return path && *path && GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES;
}

std::string seconds(int64_t milliseconds) {
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << std::fixed << std::setprecision(3) << static_cast<double>(milliseconds) / 1000.0;
    return stream.str();
}

std::string decimal(double value, int precision = 6) {
    std::ostringstream stream;
    stream.imbue(std::locale::classic());
    stream << std::fixed << std::setprecision(precision) << value;
    return stream.str();
}

std::string escape_filter_value(const std::string& value) {
    std::string escaped;
    escaped.reserve(value.size() * 2);
    for (char ch : value) {
        if (ch == '\\' || ch == ':' || ch == '\'' || ch == ',' || ch == '[' || ch == ']' || ch == ';')
            escaped.push_back('\\');
        escaped.push_back(ch);
    }
    return escaped;
}

std::wstring quote_argument(const std::wstring& argument) {
    std::wstring result = L"\"";
    size_t backslashes = 0;
    for (wchar_t ch : argument) {
        if (ch == L'\\') {
            ++backslashes;
            continue;
        }
        if (ch == L'"') {
            result.append(backslashes * 2 + 1, L'\\');
            result.push_back(L'"');
            backslashes = 0;
            continue;
        }
        result.append(backslashes, L'\\');
        backslashes = 0;
        result.push_back(ch);
    }
    result.append(backslashes * 2, L'\\');
    result.push_back(L'"');
    return result;
}

std::wstring make_command_line(const wchar_t* executable, const std::vector<std::wstring>& arguments) {
    std::wstring result = quote_argument(executable);
    for (const auto& argument : arguments) {
        result.push_back(L' ');
        result += quote_argument(argument);
    }
    return result;
}

bool is_cancelled(const volatile int32_t* flag) {
    if (!flag) return false;
    auto* value = reinterpret_cast<volatile LONG*>(const_cast<int32_t*>(flag));
    return InterlockedCompareExchange(value, 0, 0) != 0;
}

std::wstring windows_font_path() {
    std::array<wchar_t, MAX_PATH> windows{};
    const DWORD count = GetWindowsDirectoryW(windows.data(), static_cast<UINT>(windows.size()));
    if (count == 0 || count >= windows.size()) return {};
    std::filesystem::path font = std::filesystem::path(windows.data()) / L"Fonts" / L"arial.ttf";
    if (file_exists(font.c_str())) return font.wstring();
    font = std::filesystem::path(windows.data()) / L"Fonts" / L"segoeui.ttf";
    return file_exists(font.c_str()) ? font.wstring() : std::wstring{};
}

std::string make_filter_graph(int width, int height, int fps,
                              const MSVE_RenderClip* clips, int clip_count,
                              const MSVE_RenderTextLayer* text_layers, int text_layer_count,
                              const MSVE_RenderAudioTrack* audio_tracks, int audio_track_count,
                              double& total_seconds) {
    std::vector<std::string> filters;
    std::vector<double> durations;
    std::vector<double> timeline_starts(static_cast<size_t>(clip_count), 0.0);
    durations.reserve(static_cast<size_t>(clip_count));

    for (int index = 0; index < clip_count; ++index) {
        const auto& clip = clips[index];
        const double duration = static_cast<double>(clip.duration_ms) / 1000.0;
        durations.push_back(duration);
        std::string chain = "scale=" + std::to_string(width) + ":" + std::to_string(height) +
            ":force_original_aspect_ratio=" + (clip.fit_mode == 1 ? "increase" : "decrease");
        if (clip.fit_mode == 1)
            chain += ",crop=" + std::to_string(width) + ":" + std::to_string(height);
        chain += ",setsar=1,fps=" + std::to_string(fps) + ",trim=duration=" + seconds(clip.duration_ms) +
            ",setpts=PTS-STARTPTS,format=rgba";
        if (std::abs(clip.scale - 1.0) > 1e-6)
            chain += ",scale=w='max(1,iw*" + decimal(clip.scale) + ")':h='max(1,ih*" + decimal(clip.scale) + ")'";
        if (std::abs(clip.rotation_degrees) > 1e-6) {
            constexpr double pi = 3.14159265358979323846;
            chain += ",rotate=" + decimal(clip.rotation_degrees * pi / 180.0, 8) +
                ":ow=rotw(iw):oh=roth(ih):c=none";
        }
        chain += ",format=rgba,colorchannelmixer=aa=" + decimal(clip.opacity, 4) + "[fg" + std::to_string(index) + "]";
        filters.push_back("[" + std::to_string(index) + ":v]" + chain);
        filters.push_back("color=c=black:s=" + std::to_string(width) + "x" + std::to_string(height) +
            ":r=" + std::to_string(fps) + ":d=" + seconds(clip.duration_ms) + ",format=rgba[bg" +
            std::to_string(index) + "]");
        const std::string overlay_x = "(W-w)/2+W*" + decimal(clip.position_x);
        const std::string overlay_y = "(H-h)/2+H*" + decimal(clip.position_y);
        filters.push_back("[bg" + std::to_string(index) + "][fg" + std::to_string(index) +
            "]overlay=x='" + overlay_x + "':y='" + overlay_y + "':shortest=1:format=auto,format=yuv420p,settb=AVTB[raw" +
            std::to_string(index) + "]");
        std::string effect;
        if (clip.effect == 1) effect = "colorbalance=rs=0.08:gs=0.02:bs=-0.08";
        else if (clip.effect == 2) effect = "hue=s=0";
        else if (clip.effect == 3) effect = "eq=contrast=1.08:saturation=1.18";
        filters.push_back("[raw" + std::to_string(index) + "]" +
            (effect.empty() ? "null" : effect) + "[v" + std::to_string(index) + "]");
    }

    std::string current_label = "v0";
    double accumulated = durations.front();
    for (int index = 1; index < clip_count; ++index) {
        const auto& clip = clips[index];
        const double transition = clip.transition == 1
            ? std::min({static_cast<double>(clip.transition_duration_ms) / 1000.0,
                        durations[static_cast<size_t>(index - 1)] / 2.0,
                        durations[static_cast<size_t>(index)] / 2.0})
            : 0.0;
        const std::string next_label = "v" + std::to_string(index);
        const std::string output_label = "join" + std::to_string(index);
        if (transition > 0) {
            const double offset = std::max(0.0, accumulated - transition);
            timeline_starts[static_cast<size_t>(index)] = offset;
            filters.push_back("[" + current_label + "][" + next_label + "]xfade=transition=fade:duration=" +
                decimal(transition, 3) + ":offset=" + decimal(offset, 3) + "[" + output_label + "]");
            accumulated += durations[static_cast<size_t>(index)] - transition;
        } else {
            timeline_starts[static_cast<size_t>(index)] = accumulated;
            filters.push_back("[" + current_label + "][" + next_label + "]concat=n=2:v=1:a=0[" + output_label + "]");
            accumulated += durations[static_cast<size_t>(index)];
        }
        current_label = output_label;
    }
    total_seconds = accumulated;
    for (int index = 0; index < audio_track_count; ++index) {
        const auto& track = audio_tracks[index];
        total_seconds = std::max(total_seconds,
            static_cast<double>(track.timeline_start_ms + track.duration_ms) / 1000.0);
    }
    if (total_seconds > accumulated + 0.0005) {
        const std::string output_label = "audio_tail_video";
        filters.push_back("[" + current_label + "]tpad=stop_mode=clone:stop_duration=" +
            decimal(total_seconds - accumulated, 3) + ",trim=duration=" + decimal(total_seconds, 3) +
            "[" + output_label + "]");
        current_label = output_label;
    }

    const std::wstring font_path = windows_font_path();
    std::string font_utf8;
    if (!font_path.empty()) wide_to_utf8(font_path.c_str(), font_utf8);
    for (int index = 0; index < text_layer_count; ++index) {
        const auto& layer = text_layers[index];
        std::string text_path;
        std::string color;
        wide_to_utf8(layer.text_file_path, text_path);
        wide_to_utf8(layer.color, color);
        if (!color.empty() && color.front() == '#') color.erase(color.begin());
        const double start = static_cast<double>(layer.start_ms) / 1000.0;
        const double end = std::min(total_seconds, static_cast<double>(layer.start_ms + layer.duration_ms) / 1000.0);
        std::string draw = "drawtext=textfile='" + escape_filter_value(text_path) + "':expansion=none";
        if (!font_utf8.empty()) draw += ":fontfile='" + escape_filter_value(font_utf8) + "'";
        draw += ":fontsize=" + std::to_string(layer.font_size) + ":fontcolor=0x" + color + "@" + decimal(layer.opacity, 3) +
            ":x=(w-text_w)*" + decimal(layer.x, 5) + ":y=(h-text_h)*" + decimal(layer.y, 5) +
            ":enable='between(t," + decimal(start, 3) + "," + decimal(end, 3) + ")'";
        const std::string output_label = "text" + std::to_string(index);
        filters.push_back("[" + current_label + "]" + draw + "[" + output_label + "]");
        current_label = output_label;
    }

    struct AudioSource {
        int input_index;
        int64_t timeline_start_ms;
        int64_t duration_ms;
        double volume;
        int64_t fade_in_ms;
        int64_t fade_out_ms;
    };
    std::vector<AudioSource> audio_sources;
    for (int index = 0; index < clip_count; ++index) {
        const auto& clip = clips[index];
        if (!clip.is_image && clip.has_audio && clip.audio_volume > 0.0) {
            audio_sources.push_back({index,
                static_cast<int64_t>(std::llround(timeline_starts[static_cast<size_t>(index)] * 1000.0)),
                clip.duration_ms, clip.audio_volume, 0, 0});
        }
    }
    for (int index = 0; index < audio_track_count; ++index) {
        const auto& track = audio_tracks[index];
        if (track.volume > 0.0)
            audio_sources.push_back({clip_count + index, track.timeline_start_ms, track.duration_ms,
                track.volume, track.fade_in_ms, track.fade_out_ms});
    }
    for (size_t index = 0; index < audio_sources.size(); ++index) {
        const auto& source = audio_sources[index];
        const double delay_seconds = static_cast<double>(source.timeline_start_ms) / 1000.0;
        const double duration = std::min(static_cast<double>(source.duration_ms) / 1000.0,
            std::max(0.1, total_seconds - delay_seconds));
        const std::string label = "a" + std::to_string(index);
        std::string audio = "[" + std::to_string(source.input_index) + ":a]atrim=duration=" + decimal(duration, 3) +
            ",asetpts=PTS-STARTPTS,volume=" + decimal(source.volume, 3) + ",adelay=" +
            std::to_string(source.timeline_start_ms) + "|" + std::to_string(source.timeline_start_ms);
        if (source.fade_in_ms > 0)
            audio += ",afade=t=in:st=0:d=" + seconds(source.fade_in_ms);
        if (source.fade_out_ms > 0) {
            const double fade_start = std::max(0.0, duration - static_cast<double>(source.fade_out_ms) / 1000.0);
            audio += ",afade=t=out:st=" + decimal(fade_start, 3) + ":d=" + seconds(source.fade_out_ms);
        }
        audio += ",apad,atrim=duration=" + decimal(total_seconds, 3) + "[" + label + "]";
        filters.push_back(audio);
    }
    if (!audio_sources.empty()) {
        std::string mix;
        for (size_t index = 0; index < audio_sources.size(); ++index) mix += "[a" + std::to_string(index) + "]";
        mix += "amix=inputs=" + std::to_string(audio_sources.size()) + ":duration=longest:dropout_transition=0[aout]";
        filters.push_back(mix);
    }

    std::string graph;
    for (const auto& filter : filters) {
        if (!graph.empty()) graph.push_back(';');
        graph += filter;
    }
    graph += ";[" + current_label + "]null[vout]";
    return graph;
}

void report_progress(MSVE_RenderProgressCallback callback, void* user_data, int progress, const char* stage) {
    if (callback) callback(std::clamp(progress, 0, 100), stage, user_data);
}

} // namespace

int msve_render_timeline(const wchar_t* ffmpeg_path,
                         const wchar_t* output_path,
                         int width,
                         int height,
                         int fps,
                         const MSVE_RenderClip* clips,
                         int clip_count,
                         const MSVE_RenderTextLayer* text_layers,
                         int text_layer_count,
                         const MSVE_RenderAudioTrack* audio_tracks,
                         int audio_track_count,
                         int quality,
                         const volatile int32_t* cancel_flag,
                         MSVE_RenderProgressCallback progress_callback,
                         void* user_data,
                         char* error_buffer,
                         size_t error_capacity) {
    if (!file_exists(ffmpeg_path) || !output_path || !*output_path ||
        width < 64 || height < 64 || width > 3840 || height > 3840 ||
        static_cast<int64_t>(width) * height > 8'294'400 || fps < 1 || fps > 60 ||
        clip_count < 1 || clip_count > 300 || !clips || text_layer_count < 0 || text_layer_count > 100 ||
        (text_layer_count > 0 && !text_layers) || audio_track_count < 0 || audio_track_count > 20 ||
        (audio_track_count > 0 && !audio_tracks) || quality < 0 || quality > 2) {
        set_error(error_buffer, error_capacity, "Thông số kết xuất hoặc đường dẫn FFmpeg không hợp lệ.");
        return -1;
    }
    if (is_cancelled(cancel_flag)) {
        set_error(error_buffer, error_capacity, "Đã hủy kết xuất video.");
        return 1;
    }
    if (!file_exists(output_path)) {
        // The destination is a not-yet-created output file. Only its parent must exist.
        const std::filesystem::path parent = std::filesystem::path(output_path).parent_path();
        if (!parent.empty() && !std::filesystem::exists(parent)) {
            set_error(error_buffer, error_capacity, "Thư mục lưu video không tồn tại.");
            return -1;
        }
    }
    int64_t project_duration = 0;
    for (int index = 0; index < clip_count; ++index) {
        const auto& clip = clips[index];
        if (!file_exists(clip.media_path) || clip.duration_ms < 250 || clip.duration_ms > 600'000 ||
            clip.source_start_ms < 0 || clip.fit_mode < 0 || clip.fit_mode > 1 || clip.effect < 0 || clip.effect > 3 ||
            clip.transition < 0 || clip.transition > 1 || clip.transition_duration_ms < 0 ||
            !std::isfinite(clip.position_x) || !std::isfinite(clip.position_y) ||
            !std::isfinite(clip.scale) || clip.scale < 0.1 || clip.scale > 5 ||
            !std::isfinite(clip.rotation_degrees) || !std::isfinite(clip.opacity) || clip.opacity < 0 || clip.opacity > 1 ||
            !std::isfinite(clip.audio_volume) || clip.audio_volume < 0 || clip.audio_volume > 2) {
            set_error(error_buffer, error_capacity, "Một cảnh chứa media hoặc thông số không hợp lệ.");
            return -1;
        }
        project_duration += clip.duration_ms;
        if (project_duration > 1'800'000) {
            set_error(error_buffer, error_capacity, "Thời lượng dự án vượt giới hạn 30 phút.");
            return -1;
        }
    }
    for (int index = 0; index < text_layer_count; ++index) {
        const auto& layer = text_layers[index];
        std::string color;
        if (!file_exists(layer.text_file_path) || !wide_to_utf8(layer.color, color) ||
            color.size() != 7 || color.front() != '#' || layer.start_ms < 0 || layer.duration_ms < 100 ||
            layer.font_size < 8 || layer.font_size > 300 || !std::isfinite(layer.x) || !std::isfinite(layer.y) ||
            !std::isfinite(layer.opacity) || layer.opacity < 0 || layer.opacity > 1) {
            set_error(error_buffer, error_capacity, "Một lớp chữ chứa nội dung hoặc thông số không hợp lệ.");
            return -1;
        }
        for (size_t i = 1; i < color.size(); ++i) {
            if (!std::isxdigit(static_cast<unsigned char>(color[i]))) {
                set_error(error_buffer, error_capacity, "Màu chữ phải dùng mã #RRGGBB.");
                return -1;
            }
        }
    }
    for (int index = 0; index < audio_track_count; ++index) {
        const auto& track = audio_tracks[index];
        if (!file_exists(track.media_path) || track.timeline_start_ms < 0 || track.source_start_ms < 0 ||
            track.duration_ms < 100 || track.duration_ms > 3'600'000 || !std::isfinite(track.volume) ||
            track.volume < 0 || track.volume > 2 || track.fade_in_ms < 0 || track.fade_out_ms < 0) {
            set_error(error_buffer, error_capacity, "Một track âm thanh chứa media hoặc thông số không hợp lệ.");
            return -1;
        }
    }

    try {
        std::vector<std::wstring> arguments{L"-hide_banner", L"-loglevel", L"error", L"-y"};
        for (int index = 0; index < clip_count; ++index) {
            const auto& clip = clips[index];
            if (clip.is_image) {
                const auto duration = seconds(clip.duration_ms);
                arguments.insert(arguments.end(), {L"-loop", L"1", L"-framerate", std::to_wstring(fps),
                    L"-t", std::wstring(duration.begin(), duration.end()), L"-i", clip.media_path});
            } else {
                const auto seek = seconds(clip.source_start_ms);
                const auto duration = seconds(clip.duration_ms);
                arguments.insert(arguments.end(), {L"-ss",
                    std::wstring(seek.begin(), seek.end()), L"-t", std::wstring(duration.begin(), duration.end()),
                    L"-i", clip.media_path});
            }
        }
        for (int index = 0; index < audio_track_count; ++index) {
            const auto source = seconds(audio_tracks[index].source_start_ms);
            arguments.insert(arguments.end(), {L"-ss", std::wstring(source.begin(), source.end()), L"-i",
                audio_tracks[index].media_path});
        }

        double total_seconds = 0;
        const std::string graph_utf8 = make_filter_graph(width, height, fps, clips, clip_count,
            text_layers, text_layer_count, audio_tracks, audio_track_count, total_seconds);
        std::wstring graph;
        if (!utf8_to_wide(graph_utf8, graph)) {
            set_error(error_buffer, error_capacity, "Không chuyển được filter graph sang Unicode.");
            return -1;
        }
        arguments.insert(arguments.end(), {L"-filter_complex", graph, L"-map", L"[vout]"});

        bool has_audio = false;
        for (int index = 0; index < clip_count; ++index)
            has_audio = has_audio || (!clips[index].is_image && clips[index].has_audio && clips[index].audio_volume > 0);
        for (int index = 0; index < audio_track_count; ++index)
            has_audio = has_audio || audio_tracks[index].volume > 0;
        if (has_audio) arguments.insert(arguments.end(), {L"-map", L"[aout]"});
        else arguments.push_back(L"-an");

        const wchar_t* presets[] = {L"veryfast", L"medium", L"slow"};
        const wchar_t* crfs[] = {L"28", L"21", L"17"};
        arguments.insert(arguments.end(), {L"-c:v", L"libx264", L"-preset", presets[quality], L"-crf", crfs[quality],
            L"-pix_fmt", L"yuv420p"});
        if (has_audio) arguments.insert(arguments.end(), {L"-c:a", L"aac", L"-b:a", L"192k"});
        const auto duration = decimal(total_seconds, 3);
        arguments.insert(arguments.end(), {L"-t", std::wstring(duration.begin(), duration.end()), L"-movflags", L"+faststart",
            L"-progress", L"pipe:1", L"-nostats", output_path});

        SECURITY_ATTRIBUTES security{};
        security.nLength = sizeof(security);
        security.bInheritHandle = TRUE;
        HANDLE raw_read = nullptr;
        HANDLE raw_write = nullptr;
        if (!CreatePipe(&raw_read, &raw_write, &security, 0)) {
            set_error(error_buffer, error_capacity, "Không tạo được kênh theo dõi tiến trình FFmpeg.");
            return -1;
        }
        UniqueHandle pipe_read(raw_read);
        UniqueHandle pipe_write(raw_write);
        SetHandleInformation(pipe_read.get(), HANDLE_FLAG_INHERIT, 0);

        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        startup.hStdOutput = pipe_write.get();
        startup.hStdError = pipe_write.get();
        PROCESS_INFORMATION process{};
        std::wstring command = make_command_line(ffmpeg_path, arguments);
        command.push_back(L'\0');
        if (!CreateProcessW(ffmpeg_path, command.data(), nullptr, nullptr, TRUE,
            CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP, nullptr, nullptr, &startup, &process)) {
            set_error(error_buffer, error_capacity, "Không khởi chạy được FFmpeg. Kiểm tra đường dẫn và quyền chạy.");
            return -1;
        }
        UniqueHandle process_handle(process.hProcess);
        UniqueHandle thread_handle(process.hThread);
        pipe_write = UniqueHandle{};
        report_progress(progress_callback, user_data, 1, "Đang kết xuất bằng C++ / FFmpeg");

        std::string pending;
        std::vector<std::string> recent_errors;
        std::array<char, 8192> buffer{};
        bool cancelled = false;
        while (true) {
            if (is_cancelled(cancel_flag)) {
                cancelled = true;
                TerminateProcess(process_handle.get(), 1);
            }
            DWORD available = 0;
            if (!PeekNamedPipe(pipe_read.get(), nullptr, 0, nullptr, &available, nullptr)) {
                if (GetLastError() == ERROR_BROKEN_PIPE) break;
                TerminateProcess(process_handle.get(), 1);
                set_error(error_buffer, error_capacity, "Lỗi đọc tiến trình FFmpeg.");
                return -1;
            }
            if (available == 0) {
                if (WaitForSingleObject(process_handle.get(), 50) == WAIT_OBJECT_0) {
                    if (!PeekNamedPipe(pipe_read.get(), nullptr, 0, nullptr, &available, nullptr) || available == 0) break;
                } else {
                    continue;
                }
            }
            DWORD read = 0;
            if (!ReadFile(pipe_read.get(), buffer.data(), static_cast<DWORD>(std::min<size_t>(buffer.size(), available)), &read, nullptr)) {
                if (GetLastError() == ERROR_BROKEN_PIPE) break;
                continue;
            }
            pending.append(buffer.data(), read);
            size_t newline = 0;
            while ((newline = pending.find('\n')) != std::string::npos) {
                std::string line = pending.substr(0, newline);
                pending.erase(0, newline + 1);
                if (!line.empty() && line.back() == '\r') line.pop_back();
                if (line.rfind("out_time_ms=", 0) == 0 && total_seconds > 0) {
                    try {
                        const int64_t milliseconds = std::stoll(line.substr(12));
                        const int progress = 1 + static_cast<int>(std::llround(
                            std::clamp(static_cast<double>(milliseconds) / (total_seconds * 1'000'000.0), 0.0, 1.0) * 98.0));
                        report_progress(progress_callback, user_data, progress, "Đang ghép cảnh, chữ và âm thanh");
                    } catch (...) {
                    }
                } else if (!line.empty() && line.find('=') == std::string::npos) {
                    recent_errors.push_back(std::move(line));
                    if (recent_errors.size() > 12) recent_errors.erase(recent_errors.begin());
                }
            }
        }
        WaitForSingleObject(process_handle.get(), INFINITE);
        if (cancelled || is_cancelled(cancel_flag)) {
            set_error(error_buffer, error_capacity, "Đã hủy kết xuất video.");
            return 1;
        }
        DWORD exit_code = 1;
        GetExitCodeProcess(process_handle.get(), &exit_code);
        if (exit_code != 0) {
            std::string detail = "FFmpeg không thể kết xuất video.";
            if (!recent_errors.empty()) {
                detail += " ";
                const size_t first = recent_errors.size() > 4 ? recent_errors.size() - 4 : 0;
                for (size_t index = first; index < recent_errors.size(); ++index) {
                    if (index > first) detail += " | ";
                    detail += recent_errors[index];
                }
            }
            set_error(error_buffer, error_capacity, detail);
            return -1;
        }
        WIN32_FILE_ATTRIBUTE_DATA output_info{};
        if (!GetFileAttributesExW(output_path, GetFileExInfoStandard, &output_info) ||
            (output_info.nFileSizeHigh == 0 && output_info.nFileSizeLow == 0)) {
            set_error(error_buffer, error_capacity, "FFmpeg hoàn tất nhưng tệp đầu ra rỗng hoặc không tồn tại.");
            return -1;
        }
        report_progress(progress_callback, user_data, 100, "Đã xuất video");
        return 0;
    } catch (const std::exception& error) {
        set_error(error_buffer, error_capacity, std::string("Lỗi kết xuất: ") + error.what());
        return -1;
    }
}

int msve_render_ffmpeg_arguments(const wchar_t* ffmpeg_path,
                                 const wchar_t* output_path,
                                 const wchar_t* const* arguments,
                                 int argument_count,
                                 double total_seconds,
                                 const volatile int32_t* cancel_flag,
                                 MSVE_RenderProgressCallback progress_callback,
                                 void* user_data,
                                 char* error_buffer,
                                 size_t error_capacity) {
    if (!file_exists(ffmpeg_path) || !output_path || !*output_path || !arguments ||
        argument_count < 1 || argument_count > 8192 || !std::isfinite(total_seconds) ||
        total_seconds <= 0.0 || total_seconds > 1800.0) {
        set_error(error_buffer, error_capacity, "Thông số FFmpeg composition hoặc đường dẫn không hợp lệ.");
        return -1;
    }
    const std::filesystem::path parent = std::filesystem::path(output_path).parent_path();
    if (!parent.empty() && !std::filesystem::exists(parent)) {
        set_error(error_buffer, error_capacity, "Thư mục lưu composition không tồn tại.");
        return -1;
    }
    if (is_cancelled(cancel_flag)) {
        set_error(error_buffer, error_capacity, "Đã hủy kết xuất composition.");
        return 1;
    }

    try {
        std::vector<std::wstring> argument_vector;
        argument_vector.reserve(static_cast<size_t>(argument_count));
        for (int index = 0; index < argument_count; ++index) {
            if (!arguments[index]) {
                set_error(error_buffer, error_capacity, "Argument FFmpeg composition chứa giá trị rỗng.");
                return -1;
            }
            argument_vector.emplace_back(arguments[index]);
        }

        SECURITY_ATTRIBUTES security{};
        security.nLength = sizeof(security);
        security.bInheritHandle = TRUE;
        HANDLE raw_read = nullptr;
        HANDLE raw_write = nullptr;
        if (!CreatePipe(&raw_read, &raw_write, &security, 0)) {
            set_error(error_buffer, error_capacity, "Không tạo được pipe theo dõi FFmpeg composition.");
            return -1;
        }
        UniqueHandle pipe_read(raw_read);
        UniqueHandle pipe_write(raw_write);
        SetHandleInformation(pipe_read.get(), HANDLE_FLAG_INHERIT, 0);

        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        startup.hStdOutput = pipe_write.get();
        startup.hStdError = pipe_write.get();
        PROCESS_INFORMATION process{};
        std::wstring command = make_command_line(ffmpeg_path, argument_vector);
        command.push_back(L'\0');
        if (!CreateProcessW(ffmpeg_path, command.data(), nullptr, nullptr, TRUE,
            CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP, nullptr, nullptr, &startup, &process)) {
            set_error(error_buffer, error_capacity, "Không khởi chạy được FFmpeg composition.");
            return -1;
        }
        UniqueHandle process_handle(process.hProcess);
        UniqueHandle thread_handle(process.hThread);
        pipe_write = UniqueHandle{};
        report_progress(progress_callback, user_data, 1, "Đang dựng Composition Graph bằng C++ / FFmpeg");

        std::string pending;
        std::vector<std::string> recent_errors;
        std::array<char, 8192> buffer{};
        bool cancelled = false;
        bool pipe_error = false;
        while (true) {
            if (is_cancelled(cancel_flag)) {
                cancelled = true;
                TerminateProcess(process_handle.get(), 1);
            }
            DWORD available = 0;
            if (!PeekNamedPipe(pipe_read.get(), nullptr, 0, nullptr, &available, nullptr)) {
                if (GetLastError() == ERROR_BROKEN_PIPE) break;
                TerminateProcess(process_handle.get(), 1);
                pipe_error = true;
                break;
            }
            if (available == 0) {
                if (WaitForSingleObject(process_handle.get(), 50) == WAIT_OBJECT_0) {
                    if (!PeekNamedPipe(pipe_read.get(), nullptr, 0, nullptr, &available, nullptr) || available == 0)
                        break;
                } else {
                    continue;
                }
            }
            DWORD read = 0;
            if (!ReadFile(pipe_read.get(), buffer.data(), static_cast<DWORD>(std::min<size_t>(buffer.size(), available)),
                          &read, nullptr)) {
                if (GetLastError() == ERROR_BROKEN_PIPE) break;
                continue;
            }
            pending.append(buffer.data(), read);
            size_t newline = 0;
            while ((newline = pending.find('\n')) != std::string::npos) {
                std::string line = pending.substr(0, newline);
                pending.erase(0, newline + 1);
                if (!line.empty() && line.back() == '\r') line.pop_back();
                if (line.rfind("out_time_ms=", 0) == 0) {
                    try {
                        const int64_t elapsed_us = std::stoll(line.substr(12));
                        const int progress = 1 + static_cast<int>(std::llround(
                            std::clamp(static_cast<double>(elapsed_us) /
                                (total_seconds * 1'000'000.0), 0.0, 1.0) * 98.0));
                        report_progress(progress_callback, user_data, progress,
                                        "Đang ghép visual layers, text và audio");
                    } catch (...) {
                    }
                } else if (!line.empty() && line.find('=') == std::string::npos) {
                    recent_errors.push_back(std::move(line));
                    if (recent_errors.size() > 12) recent_errors.erase(recent_errors.begin());
                }
            }
        }
        WaitForSingleObject(process_handle.get(), INFINITE);
        if (cancelled || is_cancelled(cancel_flag)) {
            set_error(error_buffer, error_capacity, "Đã hủy kết xuất composition.");
            return 1;
        }
        if (pipe_error) {
            set_error(error_buffer, error_capacity, "Lỗi đọc tiến trình FFmpeg composition.");
            return -1;
        }
        DWORD exit_code = 1;
        GetExitCodeProcess(process_handle.get(), &exit_code);
        if (exit_code != 0) {
            std::string detail = "FFmpeg không thể dựng Composition Graph.";
            if (!recent_errors.empty()) {
                detail += " ";
                const size_t first = recent_errors.size() > 4 ? recent_errors.size() - 4 : 0;
                for (size_t index = first; index < recent_errors.size(); ++index) {
                    if (index > first) detail += " | ";
                    detail += recent_errors[index];
                }
            }
            set_error(error_buffer, error_capacity, detail);
            return -1;
        }
        WIN32_FILE_ATTRIBUTE_DATA output_info{};
        if (!GetFileAttributesExW(output_path, GetFileExInfoStandard, &output_info) ||
            (output_info.nFileSizeHigh == 0 && output_info.nFileSizeLow == 0)) {
            set_error(error_buffer, error_capacity, "FFmpeg hoàn tất nhưng composition output rỗng hoặc không tồn tại.");
            return -1;
        }
        report_progress(progress_callback, user_data, 100, "Đã xuất Composition Graph");
        return 0;
    } catch (const std::exception& error) {
        set_error(error_buffer, error_capacity, std::string("Lỗi native composition: ") + error.what());
        return -1;
    }
}
