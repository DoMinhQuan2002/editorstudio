using System.Diagnostics;
using System.IO;

namespace MediaStudio.Desktop.Services;

internal static class VideoCreatorRuntimeDiagnostics
{
    private static readonly object Sync = new();
    private static bool _bindingListenerAttached;
    private static readonly string LogPath = Path.Combine(
        AppContext.BaseDirectory, "video-creator-task3-2a-runtime.log");

    public static void EnableBindingDiagnostics()
    {
        if (_bindingListenerAttached) return;
        _bindingListenerAttached = true;

        var source = PresentationTraceSources.DataBindingSource;
        source.Switch.Level = SourceLevels.All;
        source.Listeners.Add(new FileTraceListener());
    }

    public static void LogNavigation(string message) => Write("NAVIGATION", message);

    public static void LogPlayback(string message) => Write("PLAYBACK", message);

    public static void LogPreviewFailure(Exception error) => Write("PREVIEW_EXCEPTION", error.ToString());

    private static void Write(string category, string message)
    {
        try
        {
            lock (Sync)
                File.AppendAllText(LogPath,
                    $"[{DateTimeOffset.UtcNow:O}] [{category}] {message}{Environment.NewLine}");
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // Diagnostics must never prevent the template screen from opening.
        }
    }

    private sealed class FileTraceListener : TraceListener
    {
        public override void Write(string? message) => Append(message ?? "");

        public override void WriteLine(string? message) => Append((message ?? "") + Environment.NewLine);

        private static void Append(string message)
        {
            try
            {
                lock (Sync)
                    File.AppendAllText(LogPath, $"[{DateTimeOffset.UtcNow:O}] [WPF_BINDING] {message}");
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            {
                // Diagnostics must never prevent the template screen from opening.
            }
        }
    }
}
