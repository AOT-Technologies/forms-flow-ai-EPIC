# Stage 1: Build forms-flow-web microfrontend
FROM node:18.20.0-alpine as web-build-stage
WORKDIR /forms-flow-web/app

# Copy package files
COPY forms-flow-web/package-lock.json forms-flow-web/package.json ./

# Install dependencies (include dev deps for build)
RUN npm config set fetch-retry-maxtimeout 120000 && \
    npm config set fetch-retry-mintimeout 20000 && \
    npm config set fetch-retries 5 && \
    npm ci --legacy-peer-deps

# Copy source code
COPY forms-flow-web/ ./

# Build the microfrontend
RUN npm run build
# Verify the build output exists
RUN echo "=== Checking build output structure ===" && \
    ls -la /forms-flow-web/app/build/ | head -20 && \
    if [ -f /forms-flow-web/app/build/forms-flow-web.js ]; then \
        echo "✓ Main file found: forms-flow-web.js"; \
    else \
        echo "✗ ERROR: forms-flow-web.js not found in build directory"; \
        ls -la /forms-flow-web/app/build/; \
        exit 1; \
    fi && \
    if [ -d /forms-flow-web/app/build/static ]; then \
        echo "✓ Static directory found, listing contents:"; \
        find /forms-flow-web/app/build/static -type f | head -10; \
    else \
        echo "Note: No static directory found (single file build)"; \
    fi
# Output: /forms-flow-web/app/build/forms-flow-web.js and potentially /forms-flow-web/app/build/static/

# Stage 2: Build root-config
FROM node:18.20.0-alpine as root-build-stage

# Set working directory
WORKDIR /forms-flow-web-root-config/app

# Set build arguments
ARG NODE_ENV
ARG MF_FORMSFLOW_WEB_URL=/mf/forms-flow-web.js
ARG MF_FORMSFLOW_NAV_URL
ARG MF_FORMSFLOW_SERVICE_URL
ARG MF_FORMSFLOW_COMPONENTS_URL
ARG MF_FORMSFLOW_ADMIN_URL
ARG MF_FORMSFLOW_REVIEW_URL
ARG MF_FORMSFLOW_SUBMISSIONS_URL


# Set environment variables
ENV MF_FORMSFLOW_WEB_URL=${MF_FORMSFLOW_WEB_URL}
ENV MF_FORMSFLOW_NAV_URL ${MF_FORMSFLOW_NAV_URL}
ENV MF_FORMSFLOW_SERVICE_URL ${MF_FORMSFLOW_SERVICE_URL}
ENV MF_FORMSFLOW_COMPONENTS_URL ${MF_FORMSFLOW_COMPONENTS_URL}
ENV MF_FORMSFLOW_ADMIN_URL ${MF_FORMSFLOW_ADMIN_URL}
ENV MF_FORMSFLOW_REVIEW_URL ${MF_FORMSFLOW_REVIEW_URL}
ENV MF_FORMSFLOW_SUBMISSIONS_URL ${MF_FORMSFLOW_SUBMISSIONS_URL}
ENV NODE_ENV ${NODE_ENV}

# Add `/app/node_modules/.bin` to $PATH
ENV PATH /forms-flow-web-root-config/app/node_modules/.bin:$PATH

# Install necessary packages
RUN apk update && apk upgrade && \
    apk add --no-cache bash git openssh

# Install and cache app dependencies
COPY forms-flow-web-root-config/package-lock.json /forms-flow-web-root-config/app/package-lock.json
COPY forms-flow-web-root-config/package.json /forms-flow-web-root-config/app/package.json
COPY forms-flow-web-root-config/env.sh /forms-flow-web-root-config/app/env.sh
# Include dev dependencies here so build tools like cross-env are available
RUN npm config set fetch-retry-maxtimeout 120000 && \
    npm config set fetch-retry-mintimeout 20000 && \
    npm config set fetch-retries 5 && \
    npm ci --legacy-peer-deps

# Copy source code
COPY forms-flow-web-root-config/ /forms-flow-web-root-config/app/

# Verify environment variable is set before build
RUN echo "=== Environment Check ===" && \
    echo "MF_FORMSFLOW_WEB_URL (ARG): ${MF_FORMSFLOW_WEB_URL}" && \
    echo "MF_FORMSFLOW_WEB_URL (ENV): $MF_FORMSFLOW_WEB_URL" && \
    env | grep MF_FORMSFLOW_WEB_URL || echo "WARNING: MF_FORMSFLOW_WEB_URL not in environment"

# Build the application with explicit environment variable
RUN if [ $NODE_ENV == "development" ]; then \
        MF_FORMSFLOW_WEB_URL="$MF_FORMSFLOW_WEB_URL" npm run build-dev:webpack; \
    else \
        MF_FORMSFLOW_WEB_URL="$MF_FORMSFLOW_WEB_URL" npm run build:webpack; \
    fi

# Verify the built HTML contains the correct URL
RUN echo "=== Verifying built HTML ===" && \
    echo "Checking for /mf/forms-flow-web.js..." && \
    if grep -q '/mf/forms-flow-web.js' /forms-flow-web-root-config/app/dist/index.html; then \
        echo "✓ SUCCESS: Found /mf/forms-flow-web.js in built HTML"; \
        echo "Showing the import map entry:"; \
        grep -o '"@formsflow/formsflow-web":"[^"]*"' /forms-flow-web-root-config/app/dist/index.html || echo "Pattern not found"; \
    else \
        echo "✗ ERROR: /mf/forms-flow-web.js NOT found in built HTML"; \
        echo "Found URLs in import map:"; \
        grep -o '"@formsflow/formsflow-web":"[^"]*"' /forms-flow-web-root-config/app/dist/index.html || \
        (echo "Checking for any formsflow-web references:" && \
         grep -i "formsflow-web" /forms-flow-web-root-config/app/dist/index.html | head -3 || \
         echo "No formsflow-web mapping found"); \
        exit 1; \
    fi


# Stage 3: Production stage
FROM nginx:1.27-alpine as production-stage

# Set label for image
LABEL Name="formsflow"

# Create directories
RUN mkdir -p /app /usr/share/nginx/html/mf
WORKDIR /usr/share/nginx/html/config

# Copy built files from root-config build stage
COPY --from=root-build-stage /forms-flow-web-root-config/app/dist /usr/share/nginx/html
COPY --from=root-build-stage /forms-flow-web-root-config/app/env.sh /usr/share/nginx/html/config

# Copy forms-flow-web microfrontend and all its assets to /mf/ directory
# Copy the entire build directory to preserve chunk files and static assets
COPY --from=web-build-stage /forms-flow-web/app/build /usr/share/nginx/html/mf
# Verify the main file was copied
RUN ls -la /usr/share/nginx/html/mf/forms-flow-web.js || \
    (echo "ERROR: forms-flow-web.js not found after copy" && exit 1) && \
    echo "=== Copied files in /mf/ ===" && \
    find /usr/share/nginx/html/mf -type f 2>/dev/null | head -15 || echo "No additional files found"

# Copy nginx configuration
COPY forms-flow-web-root-config/nginx.conf /etc/nginx/nginx.conf

# Expose port
EXPOSE 8080

# Install necessary packages
RUN apk add --no-cache bash

# Set execute permission for env.sh
RUN chmod +x /usr/share/nginx/html/config/env.sh

# Start Nginx server with environment setup
CMD ["/bin/bash", "-c", "nginx -g \"daemon off;\""]
# CMD ["/bin/bash", "-c", "/usr/share/nginx/html/config/env.sh && nginx -g \"daemon off;\""]
