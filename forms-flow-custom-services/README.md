# Flask API Project

A structured Flask API project using the Application Factory pattern.

## Project Structure

```
.
├── app/                  # Application package
│   ├── api/              # API Blueprint (endpoints)
│   ├── services/         # Business Logic Layer
│   ├── config.py         # Configuration classes
│   └── __init__.py      # App Factory
├── tests/                # Unit and Integration tests
├── .env                  # Environment variables
├── run.py                # Development server entry point
├── requirements.txt      # Dependencies
└── README.md             # This file
```

## Setup and Installation

1. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the development server:
   ```bash
   python run.py
   ```

## API Endpoints

- **Health Check**: `GET /health`
- **Greeting**: `GET /api/hello`
- **Submit Data**: `POST /api/data`

## Development

- The app uses `python-dotenv` to load environment variables from `.env`.
- Configurations are managed in `app/config.py`.
- Blueprints are used for modular routing in `app/api`.
