# Dockerfile for Frontend Service
FROM node:20-alpine

WORKDIR /app

# Copy package manifest
COPY package.json ./

# Copy build and runtime scripts, entry HTML, and source files
COPY build.js dev-server.js index.html ./
COPY src/ ./src/

# Build static assets to dist/
RUN node build.js

# Default configuration environment variables
ENV NODE_ENV=production \
    PORT=3000 \
    HOST=0.0.0.0 \
    BACKEND_URL=http://api:7860

# Expose web service port
EXPOSE 3000

# Start dev-server with built-in API proxy
CMD ["node", "dev-server.js"]

