FROM node:18-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Set environment variables
ENV HOST=0.0.0.0
ENV WDS_SOCKET_PORT=0
ENV DANGEROUSLY_DISABLE_HOST_CHECK=true

# Build the app
RUN npm run build

# Install serve to run the built app
RUN npm install -g serve

# Use non-root user
USER node

# Start the app with host settings
CMD ["serve", "-s", "build", "-l", "3000", "--no-clipboard"] 