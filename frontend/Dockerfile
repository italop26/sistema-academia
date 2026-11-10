FROM node:24-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN chown -R node:node /app
USER node
EXPOSE 5174
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
