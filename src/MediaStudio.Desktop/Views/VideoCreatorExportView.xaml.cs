using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using MediaStudio.Desktop.Services;
using MediaStudio.Desktop.ViewModels;

namespace MediaStudio.Desktop.Views;

public partial class VideoCreatorExportView : UserControl
{
    private readonly DispatcherTimer _playbackTimer;
    private VideoCreatorExportViewModel? _viewModel;
    private Uri? _activeSource;
    private bool _isSeeking;
    private bool _updatingSlider;
    private bool _isMediaOpened;
    private bool _playWhenOpened;

    public VideoCreatorExportView()
    {
        InitializeComponent();
        _playbackTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(150) };
        _playbackTimer.Tick += OnPlaybackTick;
        DataContextChanged += OnDataContextChanged;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private void OnLoaded(object sender, RoutedEventArgs e)
    {
        if (_viewModel is null) return;
        _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
        _viewModel.PropertyChanged += OnViewModelPropertyChanged;
        UpdatePreviewState();
        ConfigurePreviewSource();
    }

    private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
    {
        if (_viewModel is not null) _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
        ReleasePlayer("data-context-changed");
        _viewModel = e.NewValue as VideoCreatorExportViewModel;
        if (_viewModel is not null)
        {
            _viewModel.PropertyChanged += OnViewModelPropertyChanged;
            UpdatePreviewState();
            ConfigurePreviewSource();
        }
        else
        {
            SetPreviewStatus("", false);
        }
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(VideoCreatorExportViewModel.IsPreviewSourceVerified))
            ConfigurePreviewSource();
        if (e.PropertyName is nameof(VideoCreatorExportViewModel.PreviewStatus)
            or nameof(VideoCreatorExportViewModel.IsPreviewLoading)
            or nameof(VideoCreatorExportViewModel.HasPreviewError)
            or nameof(VideoCreatorExportViewModel.IsPreviewMediaOpened))
            UpdatePreviewState();
    }

    private void ConfigurePreviewSource()
    {
        if (_viewModel?.IsPreviewSourceVerified != true)
        {
            if (_activeSource is not null) ReleasePlayer("preview-source-not-verified");
            UpdatePreviewState();
            return;
        }

        var path = _viewModel.PreviewVideoPath;
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            _viewModel.SetPreviewPlaybackError("Không tìm thấy video preview đã xác minh trên ổ đĩa.");
            return;
        }

        try
        {
            var source = new Uri(Path.GetFullPath(path), UriKind.Absolute);
            if (source == _activeSource) return;
            ReleasePlayer("preview-source-replaced");
            _activeSource = source;
            PreviewPlayer.Source = source;
            PreviewPlayer.IsMuted = true;
            PreviewPlayer.Opacity = 0;
            PlayPauseButton.Content = "\uE768";
            SeekSlider.Value = Math.Clamp(_viewModel.CurrentSeconds, SeekSlider.Minimum, SeekSlider.Maximum);
            VideoCreatorRuntimeDiagnostics.LogPlayback(
                $"source-set project={_viewModel.DraftProjectId} revision={_viewModel.DraftRevision} " +
                $"template={_viewModel.TemplateId}/{_viewModel.TemplateVersion} path=\"{source.LocalPath}\" " +
                $"exists={File.Exists(source.LocalPath)} poster={_viewModel.PreviewPoster is not null}");
            UpdatePreviewState();
        }
        catch (Exception error) when (error is ArgumentException or IOException or UriFormatException)
        {
            VideoCreatorRuntimeDiagnostics.LogPlayback(
                $"source-error project={_viewModel.DraftProjectId} revision={_viewModel.DraftRevision} error=\"{error.Message}\"");
            _viewModel.SetPreviewPlaybackError(error.Message);
        }
    }

    private void OnPreviewMediaOpened(object sender, RoutedEventArgs e)
    {
        if (!IsCurrentSource()) return;
        if (!PreviewPlayer.NaturalDuration.HasTimeSpan)
        {
            _viewModel?.SetPreviewPlaybackError("WPF đã mở source nhưng không cung cấp duration hợp lệ.");
            return;
        }

        _isMediaOpened = true;
        var duration = PreviewPlayer.NaturalDuration.TimeSpan;
        SeekSlider.Maximum = Math.Max(0.1, duration.TotalSeconds);
        PreviewPlayer.Position = TimeSpan.FromSeconds(Math.Clamp(_viewModel?.CurrentSeconds ?? 0, 0, SeekSlider.Maximum));
        _viewModel?.MarkPreviewMediaOpened(duration);
        VideoCreatorRuntimeDiagnostics.LogPlayback(
            $"media-opened project={_viewModel?.DraftProjectId} revision={_viewModel?.DraftRevision} " +
            $"path=\"{_activeSource?.LocalPath}\" duration={duration.TotalSeconds:0.###} " +
            $"position={PreviewPlayer.Position.TotalSeconds:0.###} muted={PreviewPlayer.IsMuted}");
        UpdateTimeLabel();
        UpdatePreviewState();

        if (_playWhenOpened)
        {
            _playWhenOpened = false;
            StartPlayback();
        }
    }

    private void OnPreviewMediaFailed(object sender, ExceptionRoutedEventArgs e)
    {
        _playbackTimer.Stop();
        var message = e.ErrorException?.Message ?? "WPF MediaElement báo lỗi.";
        VideoCreatorRuntimeDiagnostics.LogPlayback(
            $"media-failed project={_viewModel?.DraftProjectId} revision={_viewModel?.DraftRevision} " +
            $"path=\"{_activeSource?.LocalPath}\" error=\"{message}\"");
        _viewModel?.SetPreviewPlaybackError(message);
        PlayPauseButton.Content = "\uE768";
        PreviewPlayer.Opacity = 0;
        ReleasePlayer("media-failed");
        UpdatePreviewState();
    }

    private void OnPreviewMediaEnded(object sender, RoutedEventArgs e)
    {
        if (!IsCurrentSource()) return;
        _playbackTimer.Stop();
        PreviewPlayer.Pause();
        PreviewPlayer.Position = TimeSpan.Zero;
        PreviewPlayer.Opacity = 0;
        PlayPauseButton.Content = "\uE768";
        _viewModel?.SetIsPreviewPlaying(false);
        _viewModel?.SetPlaybackPosition(TimeSpan.Zero);
        VideoCreatorRuntimeDiagnostics.LogPlayback(
            $"media-ended project={_viewModel?.DraftProjectId} revision={_viewModel?.DraftRevision} poster-restored=true");
        UpdatePreviewState();
    }

    private void OnPlayPause(object sender, RoutedEventArgs e)
    {
        if (_viewModel?.IsPreviewSourceVerified != true || PreviewPlayer.Source is null) return;
        if (_viewModel.IsPreviewPlaying)
        {
            PreviewPlayer.Pause();
            _viewModel.SetIsPreviewPlaying(false);
            PlayPauseButton.Content = "\uE768";
            _playbackTimer.Stop();
            VideoCreatorRuntimeDiagnostics.LogPlayback(
                $"pause project={_viewModel.DraftProjectId} revision={_viewModel.DraftRevision} position={PreviewPlayer.Position.TotalSeconds:0.###}");
            return;
        }

        if (!_isMediaOpened)
        {
            _playWhenOpened = true;
            SetPreviewStatus("Đang tải video; sẽ phát khi sẵn sàng...", true);
            return;
        }

        StartPlayback();
    }

    private void StartPlayback()
    {
        if (_viewModel?.IsPreviewSourceVerified != true || !_isMediaOpened || PreviewPlayer.Source is null) return;
        if (PreviewPlayer.Position >= PreviewPlayer.NaturalDuration.TimeSpan - TimeSpan.FromMilliseconds(50))
            PreviewPlayer.Position = TimeSpan.Zero;
        PreviewPlayer.IsMuted = MuteButton.Content?.ToString() == "🔇";
        PreviewPlayer.Opacity = 1;
        PreviewPlayer.Play();
        _viewModel.SetIsPreviewPlaying(true);
        PlayPauseButton.Content = "\uE769";
        _playbackTimer.Start();
        VideoCreatorRuntimeDiagnostics.LogPlayback(
            $"play project={_viewModel.DraftProjectId} revision={_viewModel.DraftRevision} " +
            $"position={PreviewPlayer.Position.TotalSeconds:0.###} muted={PreviewPlayer.IsMuted}");
        UpdatePreviewState();
    }

    private void OnMute(object sender, RoutedEventArgs e)
    {
        var shouldMute = MuteButton.Content?.ToString() != "🔇";
        PreviewPlayer.IsMuted = shouldMute;
        MuteButton.Content = shouldMute ? "\uE74F" : "\uE767";
        VideoCreatorRuntimeDiagnostics.LogPlayback(
            $"mute project={_viewModel?.DraftProjectId} revision={_viewModel?.DraftRevision} muted={shouldMute}");
    }

    private void OnSeekStarted(object sender, MouseButtonEventArgs e) => _isSeeking = true;

    private void OnSeekValueChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (_updatingSlider || _isSeeking || !_isMediaOpened || PreviewPlayer.Source is null) return;
        SeekTo(e.NewValue);
    }

    private void OnSeekCompleted(object sender, MouseButtonEventArgs e)
    {
        _isSeeking = false;
        if (!_isMediaOpened || PreviewPlayer.Source is null) return;
        SeekTo(SeekSlider.Value);
    }

    private void SeekTo(double seconds)
    {
        var target = Math.Clamp(seconds, 0, SeekSlider.Maximum);
        PreviewPlayer.Position = TimeSpan.FromSeconds(target);
        PreviewPlayer.Opacity = 1;
        _viewModel?.SetPlaybackPosition(PreviewPlayer.Position);
        VideoCreatorRuntimeDiagnostics.LogPlayback(
            $"seek project={_viewModel?.DraftProjectId} revision={_viewModel?.DraftRevision} " +
            $"requested={target:0.###} actual={PreviewPlayer.Position.TotalSeconds:0.###} playing={_viewModel?.IsPreviewPlaying}");
        UpdateTimeLabel();
    }

    private void OnPlaybackTick(object? sender, EventArgs e)
    {
        if (_isSeeking || _viewModel is null || !PreviewPlayer.NaturalDuration.HasTimeSpan) return;
        _viewModel.SetPlaybackPosition(PreviewPlayer.Position);
        _updatingSlider = true;
        SeekSlider.Value = Math.Clamp(PreviewPlayer.Position.TotalSeconds, 0, SeekSlider.Maximum);
        _updatingSlider = false;
        UpdateTimeLabel();
    }

    private void UpdateTimeLabel()
    {
        var current = PreviewPlayer.Position;
        var total = PreviewPlayer.NaturalDuration.HasTimeSpan ? PreviewPlayer.NaturalDuration.TimeSpan : TimeSpan.Zero;
        PreviewTimeLabel.Text = $"{current.ToString(@"mm\:ss", CultureInfo.InvariantCulture)} / {total.ToString(@"mm\:ss", CultureInfo.InvariantCulture)}";
    }

    private void UpdatePreviewState()
    {
        if (_viewModel is null)
        {
            SetPreviewStatus("", false);
            return;
        }

        var text = _viewModel.PreviewStatus;
        var show = _viewModel.IsPreviewLoading || _viewModel.HasPreviewError
            || (_viewModel.PreviewPoster is null && !string.IsNullOrWhiteSpace(text));
        SetPreviewStatus(text, show);
    }

    private void SetPreviewStatus(string text, bool visible)
    {
        PreviewStateText.Text = text;
        PreviewStateOverlay.Visibility = visible && !string.IsNullOrWhiteSpace(text)
            ? Visibility.Visible : Visibility.Collapsed;
    }

    private bool IsCurrentSource() => _viewModel?.IsPreviewSourceVerified == true
        && _activeSource is not null && PreviewPlayer.Source == _activeSource;

    private void OnUnloaded(object sender, RoutedEventArgs e)
    {
        if (_viewModel is not null) _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
        ReleasePlayer("unloaded");
    }

    private void ReleasePlayer(string reason)
    {
        _playbackTimer.Stop();
        _playWhenOpened = false;
        _isMediaOpened = false;
        try
        {
            PreviewPlayer.Stop();
            PreviewPlayer.Source = null;
        }
        catch (InvalidOperationException) { }
        PreviewPlayer.Opacity = 0;
        _activeSource = null;
        PlayPauseButton.Content = "\uE768";
        _viewModel?.SetIsPreviewPlaying(false);
        if (_viewModel is not null)
            VideoCreatorRuntimeDiagnostics.LogPlayback(
                $"source-released project={_viewModel.DraftProjectId} revision={_viewModel.DraftRevision} reason={reason}");
    }

    private void OnFullscreen(object sender, RoutedEventArgs e)
    {
        if (!IsCurrentSource() || !_isMediaOpened) return;
        var position = PreviewPlayer.Position;
        var wasPlaying = _viewModel?.IsPreviewPlaying == true;
        PreviewPlayer.Pause();
        _viewModel?.SetIsPreviewPlaying(false);
        _playbackTimer.Stop();

        var window = new Window
        {
            Title = "Media Studio — Video Preview",
            WindowStyle = WindowStyle.None,
            WindowState = WindowState.Maximized,
            Background = Brushes.Black,
            Topmost = true,
            Owner = Window.GetWindow(this),
        };
        var player = new MediaElement
        {
            Source = PreviewPlayer.Source,
            Stretch = Stretch.Uniform,
            LoadedBehavior = MediaState.Manual,
            UnloadedBehavior = MediaState.Stop,
            ScrubbingEnabled = true,
            IsMuted = PreviewPlayer.IsMuted,
        };
        var close = new Button { Content = "×", FontSize = 22, Width = 48, Height = 42, Margin = new Thickness(12) };
        close.HorizontalAlignment = HorizontalAlignment.Right;
        close.VerticalAlignment = VerticalAlignment.Top;
        close.Click += (_, _) => window.Close();
        var root = new Grid { Background = Brushes.Black };
        root.Children.Add(player);
        root.Children.Add(close);
        window.Content = root;
        window.PreviewKeyDown += (_, args) => { if (args.Key == Key.Escape) window.Close(); };
        player.MediaOpened += (_, _) =>
        {
            player.Position = position;
            if (wasPlaying) player.Play();
        };
        window.Closed += (_, _) =>
        {
            if (player.NaturalDuration.HasTimeSpan) PreviewPlayer.Position = player.Position;
            player.Stop();
            player.Source = null;
            if (wasPlaying)
            {
                PreviewPlayer.Play();
                _viewModel?.SetIsPreviewPlaying(true);
                PlayPauseButton.Content = "\uE769";
                _playbackTimer.Start();
            }
        };
        window.ShowDialog();
    }

    private void OnCopyResultPath(object sender, RoutedEventArgs e)
    {
        if (DataContext is VideoCreatorExportViewModel vm && !string.IsNullOrWhiteSpace(vm.ResultPath))
        {
            try { Clipboard.SetText(vm.ResultPath); } catch { }
        }
    }
}
