// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { 
  getAuth, 
  signInWithEmailAndPassword, 
  createUserWithEmailAndPassword,
  signInWithPopup,
  GoogleAuthProvider,
  signOut,
  onAuthStateChanged,
  sendPasswordResetEmail,
  User
} from 'firebase/auth';
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyAoiLOBkY56HNrqMTqxFkTfFVSX-NXo1wQ",
  authDomain: "project-199251516390.firebaseapp.com",
  projectId: "project-199251516390",
  storageBucket: "project-199251516390.firebasestorage.app",
  messagingSenderId: "199251516390",
  appId: "1:199251516390:web:bfb22bfb65df18c4459427",
  measurementId: "G-S9HSTJMKPC"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);

const googleProvider = new GoogleAuthProvider();

export const signInWithGoogle = async () => {
  try {
    const result = await signInWithPopup(auth, googleProvider);
    return { user: result.user, error: null };
  } catch (error: unknown) {
    return { user: null, error: error instanceof Error ? error.message : 'An unknown error occurred' };
  }
};

export const signInWithEmail = async (email: string, password: string) => {
  try {
    const result = await signInWithEmailAndPassword(auth, email, password);
    return { user: result.user, error: null };
  } catch (error: unknown) {
    return { user: null, error: error instanceof Error ? error.message : 'An unknown error occurred' };
  }
};

export const signUpWithEmail = async (email: string, password: string) => {
  try {
    const result = await createUserWithEmailAndPassword(auth, email, password);
    return { user: result.user, error: null };
  } catch (error: unknown) {
    return { user: null, error: error instanceof Error ? error.message : 'An unknown error occurred' };
  }
};

export const resetPassword = async (email: string) => {
  try {
    await sendPasswordResetEmail(auth, email);
    return { error: null };
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'An unknown error occurred' };
  }
};

export const logout = async () => {
  try {
    await signOut(auth);
    return { error: null };
  } catch (error: unknown) {
    return { error: error instanceof Error ? error.message : 'An unknown error occurred' };
  }
};

export const onAuthStateChange = (callback: (user: User | null) => void) => {
  return onAuthStateChanged(auth, callback);
};