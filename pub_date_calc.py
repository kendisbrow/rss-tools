#!/usr/bin/env python3
import sys
from datetime import datetime, timedelta

def main():
    # Basic argument validation
    if len(sys.argv) < 2:
        print("Usage: python every_two_weeks.py YYYY-MM-DD [--count N]")
        sys.exit(1)

    start_str = sys.argv[1]

    # Parse optional --count argument
    count = 10  # default
    if len(sys.argv) == 4 and sys.argv[2] == "--count":
        try:
            count = int(sys.argv[3])
        except ValueError:
            print("Error: count must be an integer")
            sys.exit(1)

    # Parse the start date
    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
    except ValueError:
        print("Error: date must be in YYYY-MM-DD format")
        sys.exit(1)

    delta = timedelta(weeks=2)

    for i in range(count):
        next_date = start_date + i * delta
        print(next_date.isoformat())

if __name__ == "__main__":
    main()
