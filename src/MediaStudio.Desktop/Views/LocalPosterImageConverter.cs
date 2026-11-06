using System.Collections.Concurrent;
using System.Globalization;
using System.IO;
using System.Windows.Data;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace MediaStudio.Desktop.Views;

/// <summary>Loads and caches local still-image poster assets only; remote preview URLs are ignored.</summary>
public sealed class LocalPosterImageConverter : IValueConverter
{
    private const int MaximumCachedPosters = 64;
    private static readonly ConcurrentDictionary<string, ImageSource> Cache = new(StringComparer.OrdinalIgnoreCase);

    public object? Convert(object value, Type targetType, object parameter, CultureInfo culture)
    {
        if (value is not string path || string.IsNullOrWhiteSpace(path)) return null;

        try
        {
            if (Uri.TryCreate(path, UriKind.Absolute, out var uri) && uri.IsFile)
                path = uri.LocalPath;
            var fullPath = Path.GetFullPath(path);
            if (!File.Exists(fullPath)) return null;
            if (Cache.TryGetValue(fullPath, out var cached)) return cached;

            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.CreateOptions = BitmapCreateOptions.DelayCreation;
            bitmap.CacheOption = BitmapCacheOption.OnDemand;
            bitmap.UriSource = new Uri(fullPath, UriKind.Absolute);
            bitmap.EndInit();
            bitmap.Freeze();

            if (Cache.Count >= MaximumCachedPosters)
                Cache.Clear();
            return Cache.GetOrAdd(fullPath, bitmap);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or FormatException
                                      or NotSupportedException or InvalidOperationException)
        {
            return null;
        }
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) =>
        throw new NotSupportedException();
}
