# Manual end-to-end run against real Gmail/Drive. Uses your token.json.
# Usage: python test_pipeline.py <candidate_id> "<candidate name>" <candidate_email>
import sys

from services.drive_service import load_settings
from services.pipeline import run_pipeline

if len(sys.argv) != 4:
    print('Usage: python test_pipeline.py <candidate_id> "<candidate name>" <candidate_email>')
    sys.exit(1)

candidate_id, candidate_name, candidate_email = sys.argv[1:]

result = run_pipeline(candidate_id, candidate_name, candidate_email, load_settings())

print("\n" + "="*50)
print(f"  Candidate : {candidate_id} - {candidate_name}")
print(f"  Status    : {result['status']}")
print(f"  Found     : {result['found']}")
print(f"  Missing   : {result['missing']}")
if result["error"]:
    print(f"  Error     : {result['error']}")
print("="*50)
