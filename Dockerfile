# Use an official Python image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy the requirements file from root to the container
COPY requirements.txt .

# Manually run the install command
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code (including the backend folder)
COPY . .

# Explicitly run your app using uvicorn
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
