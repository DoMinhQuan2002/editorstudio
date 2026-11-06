using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop.Views;

public partial class TemplatePreviewControl : UserControl
{
    private const string PlayGlyph = "\uE768";
    private const string PauseGlyph = "\uE769";
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromMilliseconds(150) };
    private TimeSpan _duration;
    private bool _ready;
    private bool _playing;
    private bool _updatingProgress;

    public TemplatePreviewControl()
    {
        InitializeComponent();
        _timer.Tick += OnTimerTick;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (IsVisible) SetSourceFromViewModel();
    }

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        ClosePlayback();
    }

    private void OnIsVisibleChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (IsVisible) SetSourceFromViewModel();
        else ClosePlayback();
    }

    private void ClosePlayback()
    {
        _timer.Stop();
        _playing = false;
        _ready = false;
        try
        {
            VideoPlayer.Stop();
            VideoPlayer.Close();
            VideoPlayer.Source = null;
        }
        catch (InvalidOperationException)
        {
            // The native playback surface may already have closed while the view was being removed.
        }
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (!IsLoaded) return;
        ClosePlayback();
        if (IsVisible) SetSourceFromViewModel();
    }

    private void SetSourceFromViewModel()
    {
        if (DataContext is not VideoCreatorTemplateDetailsViewModel { PreviewUri: { } source })
        {
            VideoPlayer.Source = null;
            return;
        }

        if (VideoPlayer.Source != source)
            VideoPlayer.Source = source;
        ProgressSlider.Value = 0;
        _duration = TimeSpan.Zero;
        TimeText.Text = "00:00 / 00:00";
        PlaybackError.Text = "";
    }

    private void OnMediaOpened(object sender, RoutedEventArgs e)
    {
        if (!IsVisible)
        {
            ClosePlayback();
            return;
        }
        _ready = true;
        _duration = VideoPlayer.NaturalDuration.HasTimeSpan
            ? VideoPlayer.NaturalDuration.TimeSpan
            : TimeSpan.Zero;
        _timer.Start();
        UpdateProgress();
    }

    private void OnMediaFailed(object sender, ExceptionRoutedEventArgs e)
    {
        _ready = false;
        _playing = false;
        _timer.Stop();
        PlaybackError.Text = "Không thể phát video preview.";
        PlayPauseButton.Content = PlayGlyph;
        if (e.ErrorException is not null)
            MediaStudio.Desktop.Services.VideoCreatorRuntimeDiagnostics.LogPreviewFailure(e.ErrorException);
    }

    private void OnPlayPauseClick(object sender, RoutedEventArgs e)
    {
        if (!_ready) return;
        if (_playing)
        {
            VideoPlayer.Pause();
            _playing = false;
            PlayPauseButton.Content = PlayGlyph;
        }
        else
        {
            VideoPlayer.Play();
            _playing = true;
            PlayPauseButton.Content = PauseGlyph;
        }
    }

    private void OnProgressChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (_updatingProgress || !_ready || _duration <= TimeSpan.Zero) return;
        try
        {
            VideoPlayer.Position = TimeSpan.FromTicks((long)(_duration.Ticks * ProgressSlider.Value));
        }
        catch (InvalidOperationException)
        {
            // Seeking is unavailable until MediaElement has opened the source.
        }
    }

    private void OnMuteClick(object sender, RoutedEventArgs e)
    {
        VideoPlayer.IsMuted = !VideoPlayer.IsMuted;
        MuteButton.Content = VideoPlayer.IsMuted ? "\uE74F" : "\uE767";
    }

    /// <summary>Plays the same demo in a borderless maximised window, resuming at the current position.</summary>
    private void OnFullscreenClick(object sender, RoutedEventArgs e)
    {
        if (VideoPlayer.Source is null) return;
        var resumeAt = _ready ? VideoPlayer.Position : TimeSpan.Zero;
        var wasPlaying = _playing;
        if (_playing) { VideoPlayer.Pause(); _playing = false; PlayPauseButton.Content = PlayGlyph; }

        var player = new MediaElement
        {
            Source = VideoPlayer.Source, LoadedBehavior = MediaState.Manual, UnloadedBehavior = MediaState.Close,
            Stretch = System.Windows.Media.Stretch.Uniform, IsMuted = VideoPlayer.IsMuted,
        };
        var window = new Window
        {
            Title = "Video demo", WindowStyle = WindowStyle.None, WindowState = WindowState.Maximized,
            Background = System.Windows.Media.Brushes.Black, Owner = Window.GetWindow(this), Content = player,
        };
        player.MediaOpened += (_, _) => { player.Position = resumeAt; player.Play(); };
        player.MediaEnded += (_, _) => { player.Position = TimeSpan.Zero; player.Play(); };
        window.KeyDown += (_, args) => { if (args.Key == System.Windows.Input.Key.Escape) window.Close(); };
        window.MouseLeftButtonUp += (_, _) => window.Close();
        window.Closed += (_, _) =>
        {
            var position = player.Position;
            player.Stop();
            player.Close();
            if (_ready) VideoPlayer.Position = position;
            UpdateProgress();
        };
        player.Play();
        window.Show();
        _ = wasPlaying;
    }

    private void OnTimerTick(object? sender, EventArgs e) => UpdateProgress();

    private void UpdateProgress()
    {
        if (!_ready) return;
        var position = VideoPlayer.Position;
        _updatingProgress = true;
        ProgressSlider.Value = _duration > TimeSpan.Zero
            ? Math.Clamp(position.TotalSeconds / _duration.TotalSeconds, 0, 1)
            : 0;
        _updatingProgress = false;
        TimeText.Text = $"{FormatTime(position)} / {FormatTime(_duration)}";
    }

    private static string FormatTime(TimeSpan time) => time.TotalHours >= 1
        ? time.ToString(@"hh\:mm\:ss")
        : time.ToString(@"mm\:ss");
}
