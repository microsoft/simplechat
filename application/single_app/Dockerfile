# Use the official Python image from the Docker Hub
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY application/single_app/requirements.txt .

RUN pip install --upgrade pip
RUN pip install --no-cache-dir wheel
# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt
# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY application/single_app .

# Expose the port the app runs on
EXPOSE 5000

# Define the command to run the application
CMD ["flask", "run", "--host=0.0.0.0"]
