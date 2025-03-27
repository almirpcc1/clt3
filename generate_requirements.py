import pkg_resources
import sys

def generate_requirements():
    packages = [
        'email-validator',
        'flask',
        'flask-sqlalchemy',
        'gunicorn',
        'psycopg2-binary',
        'qrcode',
        'requests',
        'twilio'
    ]
    
    with open('requirements.txt', 'w') as f:
        for package in packages:
            try:
                version = pkg_resources.get_distribution(package).version
                f.write(f"{package}=={version}\n")
            except pkg_resources.DistributionNotFound:
                f.write(f"{package}\n")

if __name__ == "__main__":
    generate_requirements()
    print("Generated requirements.txt file")
