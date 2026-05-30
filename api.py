"""
Plank — API server (DEPRECATED)

The bot now uses an external checker API configured via CHECKER_API_URL
in config.py or the CHECKER_API_URL environment variable.

This file is no longer needed. The external API should provide:
  GET /shopify?site={site}&cc={cc}|{mm}|{yy}|{cvv}&proxy={proxy}
  GET /check?site={site}

See config.py for details.
"""
