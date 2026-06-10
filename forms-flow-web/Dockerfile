# Base image
FROM node:18.20.0-alpine as build-stage

# Set working directory
WORKDIR /forms-flow-web/app

# Add `/app/node_modules/.bin` to $PATH
ENV PATH /forms-flow-web/app/node_modules/.bin:$PATH

# Install and cache app dependencies
COPY package-lock.json /forms-flow-web/app/package-lock.json
COPY package.json /forms-flow-web/app/package.json
RUN npm config set fetch-retry-maxtimeout 120000 && \
    npm config set fetch-retry-mintimeout 20000 && \
    npm config set fetch-retries 5 && \
    npm ci --only=production --legacy-peer-deps

# Copy source code
COPY . /forms-flow-web/app/

# Build the application
RUN npm run build

# Production stage
FROM nginx:1.27-alpine as production-stage

# Copy built files from build stage
COPY --from=build-stage /forms-flow-web/app/build /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Expose port
EXPOSE 8080

# Start Nginx server
CMD ["nginx", "-g", "daemon off;"]