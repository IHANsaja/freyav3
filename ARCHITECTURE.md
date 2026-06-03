```
freyav3/
│
├── core/
│   ├── __init__.py
│   ├── audio.py          # mic input / audio streaming
│   ├── model.py          # gemini live API connection
│   └── tools.py          # all your app-opening functions
│
├── config/
│   ├── __init__.py
│   └── freya_config.json # your master config file
│
├── main.py               # entry point, runs freya
├── requirements.txt      # dependencies
└── .env                  # your API key (never share this)
```