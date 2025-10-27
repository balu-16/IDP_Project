# Aroma Chat - Intelligent Document Chat

Aroma Chat is an intelligent document analysis application that allows users to upload PDFs and images, chat with AI, and unlock insights from their documents.

## Project Overview

This application features:
- PDF and image document upload
- AI-powered chat interface with Gemini API integration
- Quantum-enhanced search capabilities
- Both document-based and general conversation modes
- Modern React frontend with TypeScript
- FastAPI backend with Python

## How to run this project locally

**Use your preferred IDE**

You can clone this repo and run the application locally.

The only requirement is having Node.js & npm installed - [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating)

Follow these steps:

```sh
# Step 1: Clone the repository using the project's Git URL.
git clone <YOUR_GIT_URL>

# Step 2: Navigate to the project directory.
cd <YOUR_PROJECT_NAME>

# Step 3: Install the necessary dependencies.
npm i

# Step 4: Start the development server with auto-reloading and an instant preview.
npm run dev
```

**Edit a file directly in GitHub**

- Navigate to the desired file(s).
- Click the "Edit" button (pencil icon) at the top right of the file view.
- Make your changes and commit the changes.

**Use GitHub Codespaces**

- Navigate to the main page of your repository.
- Click on the "Code" button (green button) near the top right.
- Select the "Codespaces" tab.
- Click on "New codespace" to launch a new Codespace environment.
- Edit files directly within the Codespace and commit and push your changes once you're done.

## What technologies are used for this project?

This project is built with:

- Vite
- TypeScript
- React
- shadcn-ui
- Tailwind CSS

## How can I deploy this project?

You can deploy this project using various hosting platforms:

### Frontend Deployment
- Vercel, Netlify, or GitHub Pages for the React frontend
- Build the frontend using `npm run build`

### Backend Deployment
- Deploy the FastAPI backend to platforms like Railway, Render, or Heroku
- Ensure environment variables are properly configured

## Configuration

Make sure to set up the required environment variables:
- `GEMINI_API_KEY` for AI chat functionality
- Other configuration as needed for your deployment environment
