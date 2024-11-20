import React from 'react';
import Button from 'react-bootstrap/Button';

const AuthButton = ({ isAuthenticated, onSignIn }) => {
  if (isAuthenticated) return null;

  return (
    <Button 
      variant="primary" 
      onClick={onSignIn}
      size="lg"
      className="px-4 py-2"
    >
      Sign in
    </Button>
  );
};

export default AuthButton;