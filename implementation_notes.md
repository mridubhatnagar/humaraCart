# Implementation Notes

## Stock Availability
- Check stock when an item is added. Warn immediately if unavailable: "Chips is currently unavailable on Instamart."
- Do a final stock check at checkout (when the account holder says `ready to order` / `checkout`). Flag any out-of-stock items before showing the order summary.
- Both checks needed — cart can sit for days and stock changes.
