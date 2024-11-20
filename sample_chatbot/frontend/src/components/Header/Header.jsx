import React, { useState } from "react";
import Container from "react-bootstrap/Container";
import Navbar from "react-bootstrap/Navbar";
import Button from "react-bootstrap/Button";
import axios from "axios";

const Header = ({ isAuthenticated, setIsAuthenticated, handleClearResults, showClearButton, onLoadCSV }) => {
  const [customLogoFailed, setCustomLogoFailed] = useState(false);

  const handleLogoError = () => {
    setCustomLogoFailed(true);
  };

  const handleLogout = async () => {
    try {
      await axios.post("/logout");
      setIsAuthenticated(false);
    } catch (error) {
      console.error("Logout error:", error);
      alert("An error occurred during logout. Please try again.");
    }
  };

  const renderLogo = () => {
    const denodoLogo = (
      <img
        alt="Denodo company logo"
        src={`${process.env.PUBLIC_URL}/denodo.png`}
        height="22.5"
        className="d-inline-block align-top"
      />
    );

    if (!customLogoFailed) {
      return (
        <React.Fragment>
          {denodoLogo}
          {" + "}
          <img
            alt="Custom company logo"
            src={`${process.env.PUBLIC_URL}/logo.png`}
            height="22.5"
            className="d-inline-block align-top"
            onError={handleLogoError}
          />
        </React.Fragment>
      );
    } else {
      return denodoLogo;
    }
  };

  return (
    <Navbar className="bg-body-tertiary" data-bs-theme="dark" fixed="top">
      <Container fluid className="d-flex justify-content-between align-items-center">
        <Navbar.Brand href="#home" className="flex-grow-1">
          Ask a question
          {" | "}
          {renderLogo()}
        </Navbar.Brand>
        <div className="position-absolute start-50 translate-middle-x">
          {showClearButton && (
            <Button
              variant="warning"
              size="sm"
              onClick={handleClearResults}
            >
              Clear results
            </Button>
          )}
        </div>
        <div>
          {isAuthenticated && (
            <>
              <Button variant="success" size="sm" onClick={onLoadCSV} className="me-2">
                Load Unstructured CSV
              </Button>
              <Button variant="danger" size="sm" onClick={handleLogout}>
                Logout
              </Button>
            </>
          )}
        </div>
      </Container>
    </Navbar>
  );
};

export default Header;