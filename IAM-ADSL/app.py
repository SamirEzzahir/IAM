"""Development entry point for IAM-ADSL.

Run this file after installing the project in the virtual environment.
"""

from iam_adsl.routes import app
from iam_adsl.config import HOST, PORT


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
