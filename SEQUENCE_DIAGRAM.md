# HumaraCart: MCP Tool Call Flow

```mermaid
sequenceDiagram
    participant AH as Account Holder
    participant M as Member
    participant Bot as HumaraCart Bot
    participant MCP as Instamart MCP Server

    Note over AH,MCP: Setup (once)
    AH->>Bot: adds HumaraCart bot on WhatsApp
    Note over Bot: OAuth successful
    Bot->>MCP: get_addresses()
    MCP-->>Bot: all saved addresses
    Bot-->>AH: which address for the household?
    AH->>Bot: picks address
    Note over Bot: stored as Group.address_id; household created
    Bot-->>AH: setup complete, share invite link
    AH-->>M: invite link
    M->>Bot: joins household

    Note over AH,MCP: Add Item
    M->>Bot: "add milk"
    Bot->>MCP: search_products(addressId, "milk")
    MCP-->>Bot: variants (pack sizes)
    Bot-->>M: which variant? (size unspecified)
    M->>Bot: picks variant
    Bot->>MCP: update_cart(full item-set incl. picked variant)
    Bot->>MCP: get_cart()
    MCP-->>Bot: updated cart
    Bot-->>AH: broadcasts cart to all members
    Bot-->>M: broadcasts cart to all members

    Note over AH,MCP: Remove Item
    AH->>Bot: "remove milk"
    Bot->>MCP: update_cart(selectedAddressId, full item-set minus milk)
    Bot->>MCP: get_cart()
    MCP-->>Bot: updated cart
    Bot-->>AH: broadcasts cart to all members
    Bot-->>M: broadcasts cart to all members

    Note over AH,MCP: Checkout
    AH->>Bot: "checkout"
    Bot->>MCP: get_cart()
    MCP-->>Bot: cart + billBreakdown (item total, fees, grand total)
    Bot-->>AH: show full bill + delivery address
    Bot->>MCP: get_payment_options()
    MCP-->>Bot: UPI apps + QR + COD
    Bot-->>AH: payment options (text list) — confirm?
    AH->>Bot: confirms + picks UPI (or COD)
    Bot->>MCP: checkout(addressId, paymentMethod="UPI")
    MCP-->>Bot: PENDING_PAYMENT + bridgeUrl (relayable link)
    Bot-->>AH: sends the FULL bridgeUrl — tap to pay
    Note over AH: taps link, pays in UPI app → order auto-finalizes
    Bot-->>AH: broadcasts "Order placed ✓" to all members
    Bot-->>M: broadcasts "Order placed ✓" to all members
    Note over AH,MCP: only if cart ≥ ₹1000 — Swiggy blocks in-chat checkout → holder finishes in the app

    Note over AH,MCP: Order Tracking
    Bot->>MCP: track_order(orderId, lat, lng)
    MCP-->>Bot: order status
    Bot-->>AH: broadcasts status to all members
    Bot-->>M: broadcasts status to all members
```
