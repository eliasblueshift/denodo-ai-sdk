import React, { useState } from 'react';
import Modal from 'react-bootstrap/Modal';
import Button from 'react-bootstrap/Button';
import Form from 'react-bootstrap/Form';
import Spinner from 'react-bootstrap/Spinner';

const CSVUploadModal = ({ show, handleClose, onUpload }) => {
  const [file, setFile] = useState(null);
  const [description, setDescription] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile && selectedFile.name.endsWith('.csv')) {
      setFile(selectedFile);
    } else {
      alert('Please select a valid CSV file.');
      e.target.value = null;
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (file && description) {
      setIsLoading(true);
      try {
        await onUpload(file, description);
      } catch (error) {
        console.error('Error uploading CSV:', error);
        alert(error.response?.data?.error || 'An error occurred while uploading the CSV file.');
      } finally {
        setIsLoading(false);
        handleClose();
      }
    } else {
      alert('Please select a valid UTF-8 encoded CSV file and provide a description.');
    }
  };

  return (
    <Modal show={show} onHide={handleClose}>
      <Modal.Header closeButton className="custom-header-modal">
        <Modal.Title>Upload CSV File</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        <Form onSubmit={handleSubmit}>
          <Form.Group controlId="formFile" className="mb-3">
            <Form.Label>Select CSV file</Form.Label>
            <Form.Control type="file" onChange={handleFileChange} accept=".csv" />
          </Form.Group>
          <Form.Group controlId="formDescription" className="mb-3">
            <Form.Label>Description</Form.Label>
            <Form.Control
              as="textarea"
              rows={3}
              placeholder="Describe the contents of the CSV file"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Form.Group>
          <Button variant="primary" type="submit" disabled={isLoading}>
            {isLoading ? (
              <>
                <Spinner
                  as="span"
                  animation="border"
                  size="sm"
                  role="status"
                  aria-hidden="true"
                />
                <span className="ms-2">Uploading...</span>
              </>
            ) : (
              'Upload'
            )}
          </Button>
        </Form>
      </Modal.Body>
    </Modal>
  );
};

export default CSVUploadModal;
