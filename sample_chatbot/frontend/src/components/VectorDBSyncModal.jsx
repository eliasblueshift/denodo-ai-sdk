import React, { useState } from 'react';
import Modal from 'react-bootstrap/Modal';
import Button from 'react-bootstrap/Button';
import Form from 'react-bootstrap/Form';
import Spinner from 'react-bootstrap/Spinner';
import Alert from 'react-bootstrap/Alert';
import axios from 'axios';

const VectorDBSyncModal = ({ show, handleClose }) => {
  const [vdbs, setVdbs] = useState('');
  const [overwrite, setOverwrite] = useState(true);
  const [examplesPerTable, setExamplesPerTable] = useState(3);
  const [parallel, setParallel] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [response, setResponse] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    setResponse(null);

    try {
      const response = await axios.post('/sync_vdbs', {
        vdbs: vdbs.split(',').map(vdb => vdb.trim()).filter(vdb => vdb),
        overwrite,
        examples_per_table: examplesPerTable,
        parallel
      }, { timeout: 300000 }); // 300 seconds timeout

      setResponse({
        success: true,
        message: response.data.message
      });
    } catch (error) {
      setResponse({
        success: false,
        message: error.response?.data?.message || 'An error occurred during synchronization'
      });
    } finally {
      setIsLoading(false);
    }
  };

  const handleCloseAndReset = () => {
    setResponse(null);
    handleClose();
  };

  return (
    <Modal show={show} onHide={handleCloseAndReset}>
      <Modal.Header closeButton className="custom-header-modal">
        <Modal.Title>Sync VectorDB</Modal.Title>
      </Modal.Header>
      <Modal.Body>
        {response ? (
          <div className="text-center">
            {response.success ? (
              <div className="d-flex flex-column align-items-center">
                <div className="text-success mb-3">
                  <i className="bi bi-check-circle-fill" style={{ fontSize: '3rem' }}></i>
                </div>
                <Alert variant="success">{response.message}</Alert>
              </div>
            ) : (
              <div className="d-flex flex-column align-items-center">
                <div className="text-danger mb-3">
                  <i className="bi bi-x-circle-fill" style={{ fontSize: '3rem' }}></i>
                </div>
                <Alert variant="danger">{response.message}</Alert>
              </div>
            )}
          </div>
        ) : (
          <Form onSubmit={handleSubmit}>
            <Form.Group className="mb-3">
              <Form.Label>VDBs to Sync (comma-separated)</Form.Label>
              <Form.Control
                type="text"
                placeholder="Leave blank to sync all VDBs or specify a comma-separated list of VDBs to sync"
                value={vdbs}
                onChange={(e) => setVdbs(e.target.value)}
              />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Label>Examples per Table</Form.Label>
              <Form.Control
                type="number"
                min="0"
                value={examplesPerTable}
                onChange={(e) => setExamplesPerTable(parseInt(e.target.value))}
              />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Check
                type="checkbox"
                label="Overwrite existing data"
                checked={overwrite}
                onChange={(e) => setOverwrite(e.target.checked)}
              />
            </Form.Group>
            <Form.Group className="mb-3">
              <Form.Check
                type="checkbox"
                label="Enable parallel processing"
                checked={parallel}
                onChange={(e) => setParallel(e.target.checked)}
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
                  <span className="ms-2">Syncing...</span>
                </>
              ) : (
                'Sync'
              )}
            </Button>
          </Form>
        )}
      </Modal.Body>
    </Modal>
  );
};

export default VectorDBSyncModal; 