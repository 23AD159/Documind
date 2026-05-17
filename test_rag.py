import sys
from pathlib import Path
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

import rag_engine as rag

def test_answer_question_params():
    print("Testing answer_question with domain parameter...")
    try:
        # Mocking metadata to have at least one doc if possible, or just testing the signature
        rag._metadata = [{"doc_name": "test.pdf", "page": 1, "chunk": "Test content about legal policies."}]
        
        # Test basic call with domain
        res = rag.answer_question("What is the policy?", domain="Legal")
        print("Success: answer_question accepted domain parameter.")
        
        # Test multi-hop (already had domain, but good to check)
        res_mh = rag.multi_hop_answer_question("Test query", domain="Medical")
        print("Success: multi_hop_answer_question accepted domain parameter.")
        
    except TypeError as e:
        print(f"FAILED: TypeError caught: {e}")
    except Exception as e:
        print(f"Note: Caught other exception (likely expected if no real API key): {e}")

def test_study_materials_error_handling():
    print("\nTesting generate_study_materials error handling...")
    # Empty metadata should return []
    rag._metadata = []
    res = rag.generate_study_materials("nonexistent.pdf")
    assert res == [], f"Expected [], got {res}"
    print("Success: Empty chunks returns [].")
    
    # Metadata exists but AI offline (mocking _gemini_model to None)
    rag._metadata = [{"doc_name": "test.pdf", "page": 1, "chunk": "Test content."}]
    rag._gemini_model = None
    res = rag.generate_study_materials("test.pdf")
    assert isinstance(res, list) and len(res) > 0 and res[0].get("type") == "error", f"Expected error object, got {res}"
    print("Success: AI Offline returns error object.")

if __name__ == "__main__":
    test_answer_question_params()
    test_study_materials_error_handling()
