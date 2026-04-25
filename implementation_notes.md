# Implementation Notes

## Stock Availability
- Check stock when an item is added. Warn immediately if unavailable: "Chips is currently unavailable on Instamart."
- Do a final stock check when account holder sends `send cart link`. Flag any out of stock items before sending the summary.
- Both checks needed — cart can sit for days and stock changes.
