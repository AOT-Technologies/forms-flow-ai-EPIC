FROM python:3.13.9-slim-bookworm

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the application port
EXPOSE 5005

# Run the application using Gunicorn with increased timeout
CMD ["gunicorn", "--bind", "0.0.0.0:5005", "--timeout", "120", "run:app"]
