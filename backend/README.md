# Quantum PDF Chatbot Backend

A FastAPI-based backend that combines quantum computing with AI to provide enhanced PDF document search and retrieval capabilities.

## 🚀 Features

- **PDF Processing**: Upload and process PDF documents with text extraction and chunking
- **Vector Embeddings**: Generate embeddings using HuggingFace models
- **Persistent Storage**: ChromaDB with local persistence for vector storage
- **Quantum Search**: Grover's Algorithm implementation using Qiskit for enhanced search
- **RESTful API**: FastAPI with automatic OpenAPI documentation
- **Async Operations**: Full async/await support for better performance

## 🛠 Tech Stack

- **Backend Framework**: FastAPI (Python)
- **Vector Database**: ChromaDB with persistent storage
- **Quantum Computing**: Qiskit (Grover's Algorithm)
- **Embeddings**: HuggingFace Transformers
- **Chat AI**: Google Gemini API
- **PDF Processing**: PyPDF + LangChain
- **Database**: PostgreSQL (optional, for metadata)
- **Server**: Uvicorn ASGI server

## 📋 Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Google Gemini API key for chat functionality
- HuggingFace account (optional, for custom models)
- At least 4GB RAM (for quantum simulations)

## 🔧 Installation

1. **Clone the repository** (if not already done):
   ```bash
   git clone <repository-url>
   cd backend
   ```

2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   
   # On Windows
   venv\Scripts\activate
   
   # On macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**:
   ```bash
   # Copy the template
   cp .env.template .env
   
   # Edit .env with your actual values
   # At minimum, set your Gemini API key:
   # GEMINI_API_KEY="your_actual_api_key_here"
   ```

5. **Create necessary directories**:
   ```bash
   mkdir -p chroma_db logs
   ```

## ⚙️ Configuration

### Required Environment Variables

Edit your `.env` file with these essential settings:

```env
# Google Gemini API Key (get from https://makersuite.google.com/app/apikey)
GEMINI_API_KEY="your_gemini_api_key_here"

# Application settings
APP_NAME="Quantum PDF Chatbot Backend"
ENVIRONMENT="development"
DEBUG="true"

# Server configuration
HOST="0.0.0.0"
PORT="8000"
FRONTEND_URL="http://localhost:3000"
```

### Optional Configuration

- **HuggingFace**: Set `HUGGINGFACE_API_TOKEN` for fallback embeddings
- **PostgreSQL**: Configure database settings if using metadata storage
- **Quantum Settings**: Adjust `QUANTUM_MAX_QUBITS` and `QUANTUM_SHOTS`
- **PDF Processing**: Modify `CHUNK_SIZE`, `CHUNK_OVERLAP`, `MAX_FILE_SIZE_MB`

## 🚀 Running the Server

### Development Mode
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Production Mode
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Using Python directly
```bash
python -m uvicorn main:app --reload
```

The server will start at `http://localhost:8000`

## 📚 API Documentation

Once the server is running, visit:

- **Interactive API Docs**: http://localhost:8000/docs
- **ReDoc Documentation**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## 🔌 API Endpoints

### Health Check
```http
GET /health
```
Returns server status and configuration info.

### PDF Upload
```http
POST /api/upload_pdf
Content-Type: multipart/form-data

file: <PDF_FILE>
```
Uploads and processes a PDF file, storing embeddings in ChromaDB.

### Query Search
```http
POST /api/query
Content-Type: application/json

{
  "query": "What is quantum computing?",
  "top_k": 5,
  "similarity_threshold": 0.7,
  "use_quantum": true
}
```
Searches for relevant document chunks using quantum-enhanced similarity search.

### Additional Endpoints

- `GET /api/pdf_stats` - Get PDF processing statistics
- `GET /api/search_stats` - Get search service statistics
- `DELETE /api/clear_pdfs` - Clear all PDF data
- `GET /api/similar_documents/{document_id}` - Find similar documents

## 🧪 Testing the API

### 1. Upload a PDF
```bash
curl -X POST "http://localhost:8000/api/upload_pdf" \
     -H "accept: application/json" \
     -H "Content-Type: multipart/form-data" \
     -F "file=@your_document.pdf"
```

### 2. Search for content
```bash
curl -X POST "http://localhost:8000/api/query" \
     -H "accept: application/json" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "your search query here",
       "top_k": 5,
       "use_quantum": true
     }'
```

### 3. Check health
```bash
curl http://localhost:8000/health
```

## 🔬 Quantum Computing Features

### Grover's Algorithm Implementation

The backend uses Qiskit to implement Grover's Algorithm for quantum-enhanced search:

1. **Classical Similarity**: First calculates cosine similarity between query and documents
2. **Quantum Marking**: Items above similarity threshold are marked for quantum amplification
3. **Grover's Algorithm**: Amplifies probability of finding marked (relevant) items
4. **Enhanced Scoring**: Combines classical similarity with quantum probability boost

### Quantum Configuration

- `QUANTUM_MAX_QUBITS`: Maximum qubits for quantum circuits (default: 10)
- `QUANTUM_SHOTS`: Number of quantum measurements (default: 1024)
- `QUANTUM_BOOST_FACTOR`: Amplification factor for quantum results (default: 2.0)

## 📁 Project Structure

```
backend/
├── main.py                 # FastAPI application entry point
├── config.py              # Configuration and environment variables
├── requirements.txt       # Python dependencies
├── .env.template         # Environment variables template
├── README.md             # This file
├── services/
│   ├── pdf_processor.py   # PDF processing and embedding generation
│   ├── vector_store.py    # ChromaDB vector storage operations
│   └── quantum_search.py  # Quantum search with Grover's Algorithm
├── routes/
│   ├── pdf_routes.py      # PDF upload endpoints
│   └── query_routes.py    # Search and query endpoints
├── database/              # Optional PostgreSQL setup
├── utils/                 # Utility functions
├── chroma_db/            # ChromaDB persistent storage (created at runtime)
└── logs/                 # Application logs (created at runtime)
```

## 🔍 Troubleshooting

### Common Issues

1. **Import Errors**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

2. **Gemini API Errors**:
   - Verify your GEMINI_API_KEY in `.env`
   - Check your Google AI Studio account is active
   - Ensure API key has proper permissions

3. **ChromaDB Issues**:
   ```bash
   # Clear ChromaDB data
   rm -rf chroma_db/
   mkdir chroma_db
   ```

4. **Quantum Simulation Memory Issues**:
   - Reduce `QUANTUM_MAX_QUBITS` in `.env`
   - Decrease `QUANTUM_SHOTS` for faster execution

5. **PDF Processing Errors**:
   - Ensure PDF files are not corrupted
   - Check file size limits (`MAX_FILE_SIZE_MB`)
   - Verify PDF contains extractable text

### Debug Mode

Enable detailed logging:
```env
DEBUG="true"
LOG_LEVEL="DEBUG"
SHOW_ERROR_DETAILS="true"
```

## 🔒 Security Considerations

- Store API keys securely in `.env` (never commit to version control)
- Use HTTPS in production
- Configure CORS origins appropriately
- Implement rate limiting for production use
- Validate file uploads and sanitize inputs

## 📈 Performance Optimization

### For Large Document Collections

1. **Increase chunk overlap** for better context:
   ```env
   CHUNK_OVERLAP="300"
   ```

2. **Optimize quantum parameters**:
   ```env
   QUANTUM_MAX_QUBITS="8"  # Reduce for faster execution
   QUANTUM_SHOTS="512"     # Reduce for speed vs accuracy trade-off
   ```

3. **Use classical search for large datasets**:
   - Quantum search is most effective for datasets < 2^10 documents
   - Classical search automatically used for larger collections

### Production Deployment

```bash
# Use multiple workers
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

# Or use Gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section above
2. Review the API documentation at `/docs`
3. Open an issue on the repository

---

**Happy quantum searching! 🚀⚛️**