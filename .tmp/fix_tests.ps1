$path = "tests\test_history_corpus.py"
$text = Get-Content -Raw -Encoding UTF8 $path
$text = $text.Replace('repository.search_locator("перегрелось из-за пыли")', 'repository.search_locator(HistoryLocatorRequest(query="перегрелось из-за пыли"))')
$text = $text.Replace('repository.search_locator("перегрелось", limit=0)', 'repository.search_locator(HistoryLocatorRequest(query="перегрелось", limit=0))')
$text = $text.Replace('repository.search_locator("что-нибудь")', 'repository.search_locator(HistoryLocatorRequest(query="что-нибудь"))')
$text = $text.Replace('repository.search_locator("из-за пыли")', 'repository.search_locator(HistoryLocatorRequest(query="из-за пыли"))')
Set-Content -Path $path -Value $text -Encoding UTF8
