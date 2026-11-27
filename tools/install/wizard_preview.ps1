# Native drawing of the Identity preview. Every art number comes from the
# deployment tool's answer (the renderer's own MonogramStyle); nothing about the
# icon's look is decided here.

function Get-MonogramLayout {
    param($Art, [double]$GlyphX, [double]$GlyphY, [double]$GlyphWidth, [double]$GlyphHeight)

    $diameter = [double]$Art.canvas - 2 * [double]$Art.disc_margin
    $scale = [Math]::Min(
        [double]$Art.glyph_height_ratio * $diameter / $GlyphHeight,
        [double]$Art.glyph_width_ratio * $diameter / $GlyphWidth)
    return [pscustomobject]@{
        DiscX = [double]$Art.disc_margin
        DiscY = [double]$Art.disc_margin
        Diameter = $diameter
        Scale = $scale
        ShiftX = -($GlyphX + $GlyphWidth / 2)
        ShiftY = -($GlyphY + $GlyphHeight / 2)
        CenterX = [double]$Art.canvas / 2
        CenterY = [double]$Art.canvas / 2
    }
}

function New-PreviewBrush {
    param([string]$Colour)

    $brush = [Windows.Media.SolidColorBrush][Windows.Media.ColorConverter]::ConvertFromString($Colour)
    $brush.Freeze()
    return $brush
}

function New-MonogramDrawing {
    param($Art)

    $letter = [char]::ConvertFromUtf32([int]$Art.code_point)
    $text = New-Object Windows.Media.FormattedText $letter, ([Globalization.CultureInfo]::InvariantCulture),
        ([Windows.FlowDirection]::LeftToRight), (New-Object Windows.Media.Typeface 'Segoe UI Semibold'),
        100.0, ([Windows.Media.Brushes]::Black), 1.0
    $geometry = $text.BuildGeometry((New-Object Windows.Point 0, 0))
    $bounds = $geometry.Bounds
    $layout = Get-MonogramLayout $Art $bounds.X $bounds.Y $bounds.Width $bounds.Height

    $transform = New-Object Windows.Media.TransformGroup
    [void]$transform.Children.Add((New-Object Windows.Media.TranslateTransform $layout.ShiftX, $layout.ShiftY))
    [void]$transform.Children.Add((New-Object Windows.Media.ScaleTransform $layout.Scale, $layout.Scale))
    [void]$transform.Children.Add((New-Object Windows.Media.TranslateTransform $layout.CenterX, $layout.CenterY))
    $geometry.Transform = $transform

    $radius = $layout.Diameter / 2
    $disc = New-Object Windows.Media.EllipseGeometry (New-Object Windows.Point $layout.CenterX, $layout.CenterY), $radius, $radius
    $group = New-Object Windows.Media.DrawingGroup
    # An invisible full-canvas rectangle fixes the image extent; without it WPF
    # stretches the disc (not the canvas) to the target size.
    $canvas = New-Object Windows.Media.RectangleGeometry (New-Object Windows.Rect 0, 0, $Art.canvas, $Art.canvas)
    [void]$group.Children.Add((New-Object Windows.Media.GeometryDrawing ([Windows.Media.Brushes]::Transparent), $null, $canvas))
    [void]$group.Children.Add((New-Object Windows.Media.GeometryDrawing (New-PreviewBrush $Art.disc), $null, $disc))
    [void]$group.Children.Add((New-Object Windows.Media.GeometryDrawing (New-PreviewBrush $Art.glyph), $null, $geometry))
    $image = New-Object Windows.Media.DrawingImage $group
    $image.Freeze()
    return $image
}

function New-FilePreview {
    param([string]$Path, [int]$Side = 192)

    # Only called for a path that the deployment tool's check has just accepted.
    try {
        $bitmap = New-Object Windows.Media.Imaging.BitmapImage
        $bitmap.BeginInit()
        $bitmap.CacheOption = [Windows.Media.Imaging.BitmapCacheOption]::OnLoad
        $bitmap.CreateOptions = [Windows.Media.Imaging.BitmapCreateOptions]::IgnoreColorProfile
        $bitmap.DecodePixelWidth = $Side
        $bitmap.UriSource = New-Object Uri ([IO.Path]::GetFullPath($Path))
        $bitmap.EndInit()
        $bitmap.Freeze()
        return $bitmap
    } catch {
        return $null
    }
}

function New-IdentityPreviewImage {
    param($Preview)

    try {
        switch ($Preview.Kind) {
            'monogram' { return New-MonogramDrawing $Preview.Art }
            { $_ -in @('image', 'packaged') } { return New-FilePreview $Preview.Path }
        }
    } catch {
        return $null
    }
}
