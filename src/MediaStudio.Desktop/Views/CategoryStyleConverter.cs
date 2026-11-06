using System.Globalization;
using System.Windows.Data;
using System.Windows.Media;

namespace MediaStudio.Desktop.Views;

/// <summary>
/// Category name → pill colours and filter icon for the Video Editor redesign.
/// ConverterParameter: "bg", "fg" or "icon". Unknown categories use the Story (purple) look.
/// </summary>
public sealed class CategoryStyleConverter : IValueConverter
{
    private static readonly Dictionary<string, (string Bg, string Fg, string Icon)> Styles =
        new(StringComparer.OrdinalIgnoreCase)
        {
            ["Tất cả"] = ("#EEECFF", "#5A4CFA", ""),
            ["Xu hướng"] = ("#FFF1E8", "#E2622C", "🔥"),
            ["Story"] = ("#EEECFF", "#5A4CFA", ""),
            ["Carousel"] = ("#E8F4FD", "#2878B8", ""),
            ["Cut Out"] = ("#FDECF3", "#D0457E", ""),
            ["Du lịch"] = ("#E9F7EF", "#23864F", ""),
        };

    private static readonly Dictionary<string, Brush> BrushCache = new(StringComparer.OrdinalIgnoreCase);

    public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
    {
        var name = value as string ?? "";
        (string Bg, string Fg, string Icon) style =
            Styles.TryGetValue(name, out var found) ? found : ("#EEECFF", "#5A4CFA", "");
        return (parameter as string) switch
        {
            "bg" => BrushFor(style.Bg),
            "fg" => BrushFor(style.Fg),
            "icon" => style.Icon,
            "iconVisibility" => style.Icon.Length > 0 ? System.Windows.Visibility.Visible : System.Windows.Visibility.Collapsed,
            "iconBrush" => BrushFor(name.Equals("Xu hướng", StringComparison.OrdinalIgnoreCase) ? "#F0612C" : "#3B3F55"),
            _ => style.Icon,
        };
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture) =>
        throw new NotSupportedException();

    private static Brush BrushFor(string hex)
    {
        if (BrushCache.TryGetValue(hex, out var cached)) return cached;
        var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
        brush.Freeze();
        BrushCache[hex] = brush;
        return brush;
    }
}
