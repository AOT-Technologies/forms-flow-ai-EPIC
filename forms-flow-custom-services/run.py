import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from dotenv import load_dotenv
from formsflow_custom_services import create_app

# Load environment variables
load_dotenv()

config_name = os.getenv('FLASK_ENV', 'production')
app = create_app(config_name)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5005))
    app.run(host='0.0.0.0', port=port)
