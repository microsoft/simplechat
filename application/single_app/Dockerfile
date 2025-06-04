# Use the official Ubuntu Python image from the Docker Hub
FROM python:3.12-ubuntu

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY application/single_app/requirements.txt .

RUN apt-get update && \
    apt-get install -y \
        build-essential \
        python3-dev \
        libffi-dev \
        libssl-dev \
    && apt-get upgrade -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY application/single_app .

# Expose the port the app runs on
EXPOSE 5000

# Define the command to run the application
CMD ["flask", "run", "--host=0.0.0.0"]
