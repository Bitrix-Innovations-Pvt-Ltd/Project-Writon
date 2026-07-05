import json
import re

def parse_courts(file_path):
    courts_data = {}
    current_state = None
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            # Match state header, e.g. "Andaman and Nicobar Islands (1)"
            state_match = re.match(r'^([a-zA-Z\s&]+)\s*\(\d+\)', line)
            if state_match:
                current_state = state_match.group(1).strip()
                courts_data[current_state] = []
            else:
                # Match court line, e.g. "1. District and Sessions Court, South Andaman"
                court_match = re.match(r'^\d+\.\s*(.+)$', line)
                if court_match and current_state:
                    court_name = court_match.group(1).strip()
                    courts_data[current_state].append(court_name)
                    
    with open('district_courts.json', 'w', encoding='utf-8') as f:
        json.dump(courts_data, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    parse_courts('district_courts_raw.txt')
